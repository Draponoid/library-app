import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from contextlib import closing

from app import create_app, seed_demo


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'test.sqlite3')
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test-only-secret-' * 4, 'DATABASE': self.path})
        os.environ['DEMO_LIBRARIAN_PASSWORD'] = 'Test-Library-2026!'
        os.environ['DEMO_READER_PASSWORD'] = 'Test-Reader-2026!'
        seed_demo(self.app)
        self.client = self.app.test_client()
        self.csrf = None

    def tearDown(self):
        self.temp.cleanup()

    def login(self, role='librarian', client=None):
        client = client or self.client
        password = 'Test-Library-2026!' if role == 'librarian' else 'Test-Reader-2026!'
        result = client.post('/api/auth/login', json={'username': role, 'password': password})
        self.assertEqual(result.status_code, 200)
        self.csrf = result.json['csrf_token']
        return self.csrf

    def write(self, url, data=None, method='POST'):
        return self.client.open(url, method=method, json=data, headers={'X-CSRF-Token': self.csrf or ''})

    def sql(self, sql, params=()):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            return conn.execute(sql, params).fetchall()

    def test_health_and_web(self):
        self.assertEqual(self.client.get('/health').json['status'], 'ok')
        with self.client.get('/') as response:
            self.assertEqual(response.status_code, 200)
        with self.client.get('/static/app.js') as response:
            self.assertEqual(response.status_code, 200)

    def test_auth_required(self):
        for url in ['/api/books', '/api/readers', '/api/loans', '/api/reports', '/api/audit']:
            self.assertEqual(self.client.get(url).status_code, 401)

    def test_login_logout_and_password_hash(self):
        self.assertEqual(self.client.post('/api/auth/login', json={'username':'librarian','password':'incorrect'}).status_code, 401)
        self.login()
        self.assertEqual(self.client.get('/api/auth/me').json['user']['role'], 'librarian')
        self.assertTrue(self.sql('SELECT password_hash FROM users')[0][0].startswith('scrypt:'))
        self.assertEqual(self.write('/api/auth/logout', {}).status_code, 200)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)
        self.assertEqual(self.sql('SELECT COUNT(*) FROM sessions')[0][0], 0)

    def test_registration(self):
        data={'username':'student','password':'StrongPassword2026!','full_name':'Новый читатель','faculty_id':1}
        self.assertEqual(self.client.post('/api/auth/register', json=data).status_code, 201)
        self.assertEqual(self.sql("SELECT role FROM users WHERE username='student'")[0][0], 'reader')
        self.assertEqual(self.client.post('/api/auth/register', json=data).status_code, 409)
        self.assertEqual(self.client.post('/api/auth/register', json={**data,'username':'other','role':'librarian'}).status_code, 422)

    def test_registration_validation(self):
        data={'username':'student','password':'StrongPassword2026!','full_name':'Новый читатель','faculty_id':1}
        for patch in [{'password':'short'}, {'faculty_id':999}, {'username':'bad space'}, {'faculty_id':True}, {'full_name':[]}]:
            self.assertEqual(self.client.post('/api/auth/register', json={**data,**patch}).status_code, 422)

    def test_reader_permissions(self):
        self.login('reader')
        self.assertEqual(self.client.get('/api/books').status_code, 200)
        for url in ['/api/readers','/api/reports','/api/audit']:
            self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.write('/api/authors', {'name':'New'}).status_code, 403)
        self.assertEqual(self.write('/api/loans', {'copy_id':1,'reader_id':2}).status_code, 403)

    def test_csrf_and_cross_origin(self):
        self.login()
        self.assertEqual(self.client.post('/api/authors', json={'name':'New'}).status_code, 403)
        self.assertEqual(self.client.post('/api/authors', json={'name':'New'}, headers={'X-CSRF-Token': self.csrf,'Origin':'https://example.org'}).status_code, 403)
        self.assertEqual(self.client.post('/api/authors', json={'name':'New'}, headers={'X-CSRF-Token': self.csrf,'Sec-Fetch-Site':'cross-site'}).status_code, 403)

    def test_expired_session(self):
        self.login()
        self.sql('UPDATE sessions SET expires_at=0')
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)

    def test_crud_all_entities(self):
        self.login()
        objects=[('authors',{'name':'Тестовый автор'}),('branches',{'name':'Тестовый филиал','address':'Адрес'}),('faculties',{'name':'Тестовый факультет'}),('books',{'title':'Тестовая книга','author_id':1,'year':2026,'isbn':'TEST-123'}),('copies',{'book_id':1,'branch_id':1,'inventory_number':'TEST-INV'})]
        for entity,data in objects:
            result=self.write('/api/'+entity,data)
            self.assertEqual(result.status_code,201,result.json)
            ident=result.json['id']
            self.assertEqual(self.write(f'/api/{entity}/{ident}',data,'PUT').status_code,200)
            self.assertEqual(self.write(f'/api/{entity}/{ident}',method='DELETE').status_code,200)
            self.assertEqual(self.write(f'/api/{entity}/{ident}',data,'PUT').status_code,404)

    def test_validation_errors(self):
        self.login()
        for data in [{'title':'Test','author_id':999,'year':2020,'isbn':'1'}, {'title':'Test','author_id':1,'year':'bad','isbn':'1'}, {'title':'','author_id':1,'year':2020,'isbn':'1'}, {'title':'Test','author_id':1,'year':True,'isbn':'1'}]:
            self.assertEqual(self.write('/api/books',data).status_code,422)
        self.assertEqual(self.client.post('/api/books',data='{bad',content_type='application/json',headers={'X-CSRF-Token':self.csrf}).status_code,400)
        self.assertEqual(self.write('/api/books',[]).status_code,400)

    def test_foreign_key_delete_guard(self):
        self.login()
        self.assertEqual(self.write('/api/authors/1',method='DELETE').status_code,409)
        self.assertEqual(self.write('/api/books/1',method='DELETE').status_code,409)

    def test_search_and_filters(self):
        self.login()
        self.assertEqual(len(self.client.get('/api/books?q=МАСТЕР').json['items']),1)
        self.assertEqual(len(self.client.get('/api/books?author_id=1&branch_id=1&available=true').json['items']),1)
        self.assertEqual(self.client.get('/api/books?author_id=wrong').status_code,422)
        self.assertEqual(self.client.get('/api/books?available=maybe').status_code,422)
        self.assertEqual(self.client.get('/api/books?q=%27%20OR%201%3D1--').json['items'],[])

    def test_issue_return_and_history(self):
        self.login()
        result=self.write('/api/loans',{'copy_id':1,'reader_id':2})
        self.assertEqual(result.status_code,201)
        ident=result.json['id']
        self.assertEqual(self.write('/api/loans',{'copy_id':1,'reader_id':2}).status_code,409)
        loan=self.client.get('/api/loans').json['items'][0]
        self.assertEqual(loan['due_at'],(date.today()+timedelta(days=14)).isoformat())
        self.assertEqual(self.write('/api/copies/1',{'book_id':2,'branch_id':1,'inventory_number':'x'},'PUT').status_code,409)
        self.assertEqual(self.write('/api/loans/'+str(ident)+'/return',{}).status_code,200)
        self.assertEqual(self.write('/api/loans/'+str(ident)+'/return',{}).status_code,409)
        self.assertEqual(self.write('/api/loans',{'copy_id':1,'reader_id':2}).status_code,201)
        self.assertEqual(self.write('/api/copies/1',method='DELETE').status_code,409)

    def test_loan_limit(self):
        self.login()
        for copy_id in range(1,6):
            self.assertEqual(self.write('/api/loans',{'copy_id':copy_id,'reader_id':2}).status_code,201)
        self.assertEqual(self.write('/api/loans',{'copy_id':6,'reader_id':2}).status_code,409)

    def test_overdue_blocks_new_loan(self):
        self.login()
        self.write('/api/loans',{'copy_id':1,'reader_id':2})
        yesterday=(date.today()-timedelta(days=1)).isoformat()
        self.sql('UPDATE loans SET issued_at=?,due_at=?',(yesterday,yesterday))
        self.assertEqual(self.write('/api/loans',{'copy_id':2,'reader_id':2}).status_code,409)
        self.assertEqual(self.client.get('/api/reports').json['overdue'],1)

    def test_concurrent_issue_is_atomic(self):
        clients=[self.app.test_client(),self.app.test_client()]
        tokens=[self.login(client=c) for c in clients]
        def issue(i):
            return clients[i].post('/api/loans',json={'copy_id':1,'reader_id':2},headers={'X-CSRF-Token':tokens[i]}).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(issue,[0,1]))
        self.assertEqual(sorted(results),[201,409])
        self.assertEqual(self.sql('SELECT COUNT(*) FROM loans WHERE returned_at IS NULL')[0][0],1)

    def test_readers_see_only_own_loans(self):
        self.login()
        self.write('/api/loans',{'copy_id':1,'reader_id':2})
        self.write('/api/auth/logout',{})
        data={'username':'other','password':'StrongPassword2026!','full_name':'Другой читатель','faculty_id':1}
        self.client.post('/api/auth/register',json=data)
        self.client.post('/api/auth/login',json={'username':'other','password':data['password']})
        self.assertEqual(self.client.get('/api/loans').json['items'],[])

    def test_reports_and_audit(self):
        self.login()
        self.write('/api/loans',{'copy_id':1,'reader_id':2})
        report=self.client.get('/api/reports').json
        self.assertEqual((report['books'],report['copies'],report['active_loans']),(4,8,1))
        self.assertEqual(report['popular'][0]['loan_count'],1)
        self.assertEqual(sum(r['loan_count'] for r in report['faculties']),1)
        self.assertEqual(self.client.get('/api/audit').json['items'][0]['action'],'issue')

    def test_backup_snapshot(self):
        backup=Path(self.temp.name)/'backup.sqlite3'
        with closing(sqlite3.connect(self.path)) as source, closing(sqlite3.connect(backup)) as target:
            source.backup(target)
        with closing(sqlite3.connect(backup)) as conn:
            self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM books').fetchone()[0],4)

    def test_json_errors_and_headers(self):
        self.login()
        self.assertEqual(self.client.get('/api/missing').status_code,404)
        self.assertEqual(self.client.patch('/api/books',headers={'X-CSRF-Token':self.csrf}).status_code,405)
        response=self.client.get('/api/books')
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertIn("default-src 'self'",response.headers['Content-Security-Policy'])


if __name__ == '__main__':
    unittest.main()
