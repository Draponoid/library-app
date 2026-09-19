"""Library laboratory application. Run `python app.py --help`."""
import argparse
import hashlib
import os
from pathlib import Path
import secrets
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from contextlib import closing

from dotenv import load_dotenv
from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).resolve().parent
CATALOG = {
    'authors': ('name',), 'branches': ('name', 'address'),
    'faculties': ('name',), 'books': ('title', 'author_id', 'year', 'isbn'),
    'copies': ('book_id', 'branch_id', 'inventory_number'),
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class APIError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def db():
    if 'db' not in g:
        g.db = sqlite3.connect(g.app_db, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db


def payload():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise APIError('Ожидается JSON-объект.', 400)
    return data


def string(data, key, minimum=1, maximum=200):
    value = data.get(key)
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise APIError(f'Поле {key}: строка длиной от {minimum} до {maximum} символов.', 422)
    return value.strip()


def integer(data, key, minimum=1, maximum=2147483647):
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise APIError(f'Поле {key}: целое число от {minimum} до {maximum}.', 422)
    return value


def exists(table, ident):
    if not db().execute(f'SELECT 1 FROM {table} WHERE id=?', (ident,)).fetchone():
        raise APIError('Связанная запись не найдена.', 422)


def audit(action, entity, ident):
    db().execute('INSERT INTO audit_events(actor_id,action,entity,entity_id,created_at) VALUES(?,?,?,?,?)',
                 (g.user['id'], action, entity, ident, now()))


def auth(librarian=False):
    def decorate(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            if not g.user:
                raise APIError('Требуется вход в систему.', 401)
            if librarian and g.user['role'] != 'librarian':
                raise APIError('Действие доступно только библиотекарю.', 403)
            return func(*args, **kwargs)
        return wrapped
    return decorate


def create_app(config=None):
    load_dotenv(ROOT / '.env')
    app = Flask(__name__, static_folder='static')
    app.config.update(
        SECRET_KEY=os.getenv('SECRET_KEY'),
        DATABASE=str(ROOT / os.getenv('DATABASE_PATH', 'data/library.sqlite3')),
        SESSION_HOURS=int(os.getenv('SESSION_HOURS', '8')),
        COOKIE_SECURE=os.getenv('COOKIE_SECURE', 'false').lower() == 'true',
        LOAN_DAYS=int(os.getenv('LOAN_DAYS', '14')),
        MAX_ACTIVE_LOANS=int(os.getenv('MAX_ACTIVE_LOANS', '5')),
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    if config:
        app.config.update(config)
    if not app.config['SECRET_KEY'] or len(app.config['SECRET_KEY']) < 32 or app.config['SECRET_KEY'].startswith('replace-'):
        raise RuntimeError('Задайте случайный SECRET_KEY длиной не менее 32 символов в .env.')
    if any(app.config[k] < 1 for k in ('SESSION_HOURS', 'LOAN_DAYS', 'MAX_ACTIVE_LOANS')):
        raise RuntimeError('SESSION_HOURS, LOAN_DAYS, MAX_ACTIVE_LOANS должны быть положительными.')
    Path(app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(app.config['DATABASE'])) as conn:
        conn.executescript((ROOT / 'schema.sql').read_text(encoding='utf-8'))
        conn.execute('PRAGMA journal_mode=WAL')

    @app.before_request
    def load_user():
        g.app_db, g.user, g.session = app.config['DATABASE'], None, None
        token = request.cookies.get('library_session', '')
        if token:
            hashed = hashlib.sha256(token.encode()).hexdigest()
            row = db().execute('SELECT * FROM sessions WHERE token_hash=? AND expires_at>?', (hashed, int(time.time()))).fetchone()
            if row:
                g.session = row
                g.user = db().execute('SELECT id,username,full_name,role,faculty_id FROM users WHERE id=?', (row['user_id'],)).fetchone()
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            # Browser cross-site submissions, including login, are never accepted.
            origin = request.headers.get('Origin')
            if (origin and origin != request.host_url.rstrip('/')) or request.headers.get('Sec-Fetch-Site') == 'cross-site':
                raise APIError('Запрос с другого сайта отклонён.', 403)
            if g.user and not secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), g.session['csrf_token']):
                raise APIError('Некорректный CSRF-токен. Обновите страницу.', 403)

    @app.teardown_appcontext
    def close_db(_error):
        conn = g.pop('db', None)
        if conn:
            conn.close()

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.errorhandler(APIError)
    def api_error(error):
        return jsonify(error={'message': error.message, 'status': error.status}), error.status

    @app.errorhandler(sqlite3.IntegrityError)
    def integrity_error(_error):
        return jsonify(error={'message': 'Конфликт: запись уже существует, используется или нарушает правило данных.', 'status': 409}), 409

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error={'message': error.description, 'status': error.code}), error.code

    @app.errorhandler(Exception)
    def unexpected(error):
        app.logger.exception('Request failed')
        return jsonify(error={'message': 'Внутренняя ошибка сервера.', 'status': 500}), 500

    @app.get('/')
    def index():
        return send_from_directory(app.static_folder, 'index.html')

    @app.get('/health')
    def health():
        db().execute('SELECT 1 FROM books').fetchone()
        return jsonify(status='ok', version='0.1.0', database='ok')

    @app.post('/api/auth/register')
    def register():
        data = payload()
        if set(data) - {'username', 'password', 'full_name', 'faculty_id'}:
            raise APIError('Недопустимые поля регистрации.', 422)
        username = string(data, 'username', 3, 50).lower()
        if not all(c.isascii() and (c.isalnum() or c in '._-') for c in username):
            raise APIError('Логин: латинские буквы, цифры, точка, дефис и подчёркивание.', 422)
        password = string(data, 'password', 10, 128)
        name, faculty = string(data, 'full_name', 2, 120), integer(data, 'faculty_id')
        exists('faculties', faculty)
        with db():
            cursor = db().execute("INSERT INTO users(username,password_hash,full_name,role,faculty_id) VALUES(?,?,?,'reader',?)",
                                  (username, generate_password_hash(password), name, faculty))
        return jsonify(id=cursor.lastrowid, message='Регистрация завершена. Войдите в систему.'), 201

    @app.post('/api/auth/login')
    def login():
        data = payload()
        username, password = string(data, 'username', 1, 50).lower(), string(data, 'password', 1, 128)
        user = db().execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        if not user or not check_password_hash(user['password_hash'], password):
            raise APIError('Неверный логин или пароль.', 401)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with db():
            if g.session:
                db().execute('DELETE FROM sessions WHERE token_hash=?', (g.session['token_hash'],))
            db().execute('DELETE FROM sessions WHERE expires_at<=?', (int(time.time()),))
            db().execute('INSERT INTO sessions VALUES(?,?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), user['id'], csrf,
                          int(time.time()) + app.config['SESSION_HOURS'] * 3600))
        response = jsonify(user={k: user[k] for k in ('id', 'username', 'full_name', 'role', 'faculty_id')}, csrf_token=csrf)
        response.set_cookie('library_session', token, httponly=True, secure=app.config['COOKIE_SECURE'], samesite='Lax',
                            max_age=app.config['SESSION_HOURS'] * 3600)
        return response

    @app.get('/api/auth/me')
    @auth()
    def me():
        return jsonify(user=dict(g.user), csrf_token=g.session['csrf_token'])

    @app.post('/api/auth/logout')
    @auth()
    def logout():
        with db():
            db().execute('DELETE FROM sessions WHERE token_hash=?', (g.session['token_hash'],))
        response = jsonify(message='Вы вышли из системы.')
        response.delete_cookie('library_session')
        return response

    @app.get('/api/faculties/public')
    def public_faculties():
        return jsonify(items=[dict(r) for r in db().execute('SELECT * FROM faculties ORDER BY name')])

    @app.get('/api/<entity>')
    @auth()
    def list_entities(entity):
        if entity not in CATALOG:
            raise APIError('Ресурс не найден.', 404)
        if entity == 'books':
            rows = db().execute('''SELECT b.*, a.name AS author,
                (SELECT COUNT(*) FROM copies c WHERE c.book_id=b.id) AS total_copies,
                (SELECT COUNT(*) FROM copies c WHERE c.book_id=b.id AND NOT EXISTS
                  (SELECT 1 FROM loans l WHERE l.copy_id=c.id AND l.returned_at IS NULL)) AS available_copies
                FROM books b JOIN authors a ON a.id=b.author_id ORDER BY b.title''').fetchall()
            query, author_id, branch_id = request.args.get('q', '').casefold(), request.args.get('author_id'), request.args.get('branch_id')
            for key, value in [('author_id', author_id), ('branch_id', branch_id)]:
                if value is not None and (not value.isascii() or not value.isdecimal() or int(value) < 1):
                    raise APIError(f'{key}: ожидается положительное целое число.', 422)
            if request.args.get('available') not in (None, 'true', 'false'):
                raise APIError('available: допустимы true или false.', 422)
            items = [dict(r) for r in rows if query in (r['title'] + ' ' + r['author'] + ' ' + r['isbn']).casefold()
                     and (not author_id or r['author_id'] == int(author_id))]
            if branch_id:
                ids = {r[0] for r in db().execute('SELECT DISTINCT book_id FROM copies WHERE branch_id=?', (int(branch_id),))}
                items = [r for r in items if r['id'] in ids]
            if request.args.get('available') == 'true':
                if branch_id:
                    ids = {r[0] for r in db().execute('''SELECT DISTINCT c.book_id FROM copies c WHERE branch_id=? AND NOT EXISTS
                        (SELECT 1 FROM loans l WHERE l.copy_id=c.id AND returned_at IS NULL)''', (int(branch_id),))}
                    items = [r for r in items if r['id'] in ids]
                else:
                    items = [r for r in items if r['available_copies'] > 0]
            return jsonify(items=items)
        if entity == 'copies':
            rows = db().execute('''SELECT c.*, b.title, br.name AS branch,
                CASE WHEN EXISTS(SELECT 1 FROM loans l WHERE l.copy_id=c.id AND l.returned_at IS NULL)
                THEN 'on_loan' ELSE 'available' END AS status
                FROM copies c JOIN books b ON b.id=c.book_id JOIN branches br ON br.id=c.branch_id ORDER BY c.id''')
        else:
            rows = db().execute(f'SELECT * FROM {entity} ORDER BY name')
        return jsonify(items=[dict(r) for r in rows])

    def validated(entity, data):
        fields = CATALOG[entity]
        if set(data) != set(fields):
            raise APIError('Нужны ровно поля: ' + ', '.join(fields), 422)
        result = {}
        for key in fields:
            if key.endswith('_id'):
                value = integer(data, key)
                exists({'author_id': 'authors', 'book_id': 'books', 'branch_id': 'branches'}[key], value)
            elif key == 'year':
                value = integer(data, key, 1450, 2100)
            else:
                value = string(data, key, maximum=120 if key in ('name', 'inventory_number', 'isbn') else 200)
            result[key] = value
        return result

    @app.route('/api/<entity>', methods=['POST'])
    @app.route('/api/<entity>/<int:ident>', methods=['PUT', 'DELETE'])
    @auth(librarian=True)
    def modify(entity, ident=None):
        if entity not in CATALOG:
            raise APIError('Ресурс не найден.', 404)
        with db():
            # Serialize read-check-write steps, including changes to a borrowed copy.
            db().execute('BEGIN IMMEDIATE')
            if ident is not None and not db().execute(f'SELECT 1 FROM {entity} WHERE id=?', (ident,)).fetchone():
                raise APIError('Запись не найдена.', 404)
            if entity == 'copies' and ident is not None and db().execute(
                    'SELECT 1 FROM loans WHERE copy_id=? AND returned_at IS NULL', (ident,)).fetchone():
                raise APIError('Нельзя менять или удалять выданный экземпляр.', 409)
            if request.method == 'DELETE':
                db().execute(f'DELETE FROM {entity} WHERE id=?', (ident,))
            else:
                values = validated(entity, payload())
                if ident is None:
                    cursor = db().execute(f'INSERT INTO {entity} ({",".join(values)}) VALUES ({",".join("?" for _ in values)})', tuple(values.values()))
                    ident = cursor.lastrowid
                else:
                    db().execute(f'UPDATE {entity} SET {",".join(k+"=?" for k in values)} WHERE id=?', (*values.values(), ident))
            audit(request.method.lower(), entity, ident)
        return jsonify(id=ident), 201 if request.method == 'POST' else 200

    @app.get('/api/readers')
    @auth(librarian=True)
    def readers():
        return jsonify(items=[dict(r) for r in db().execute("""SELECT u.id,u.username,u.full_name,u.faculty_id,f.name AS faculty
            FROM users u LEFT JOIN faculties f ON f.id=u.faculty_id WHERE role='reader' ORDER BY full_name""")])

    @app.get('/api/loans')
    @auth()
    def loans():
        query = '''SELECT l.*, b.title, c.inventory_number, u.full_name AS reader,
            CASE WHEN l.returned_at IS NULL AND l.due_at < ? THEN 1 ELSE 0 END AS overdue
            FROM loans l JOIN copies c ON c.id=l.copy_id JOIN books b ON b.id=c.book_id
            JOIN users u ON u.id=l.reader_id'''
        args = [date.today().isoformat()]
        if g.user['role'] == 'reader':
            query += ' WHERE l.reader_id=?'
            args.append(g.user['id'])
        return jsonify(items=[dict(r) for r in db().execute(query + ' ORDER BY l.id DESC', args)])

    @app.post('/api/loans')
    @auth(librarian=True)
    def issue():
        data = payload()
        if set(data) != {'copy_id', 'reader_id'}:
            raise APIError('Нужны copy_id и reader_id.', 422)
        copy_id, reader_id = integer(data, 'copy_id'), integer(data, 'reader_id')
        today = date.today()
        with db():
            db().execute('BEGIN IMMEDIATE')
            exists('copies', copy_id)
            reader = db().execute("SELECT 1 FROM users WHERE id=? AND role='reader'", (reader_id,)).fetchone()
            if not reader:
                raise APIError('Читатель не найден.', 422)
            if db().execute('SELECT 1 FROM loans WHERE copy_id=? AND returned_at IS NULL', (copy_id,)).fetchone():
                raise APIError('Экземпляр уже выдан.', 409)
            active = db().execute('SELECT COUNT(*) FROM loans WHERE reader_id=? AND returned_at IS NULL', (reader_id,)).fetchone()[0]
            if active >= app.config['MAX_ACTIVE_LOANS']:
                raise APIError('Достигнут лимит активных выдач.', 409)
            if db().execute('SELECT 1 FROM loans WHERE reader_id=? AND returned_at IS NULL AND due_at<?', (reader_id, today.isoformat())).fetchone():
                raise APIError('Сначала верните просроченные книги.', 409)
            cursor = db().execute('INSERT INTO loans(copy_id,reader_id,issued_at,due_at) VALUES(?,?,?,?)',
                (copy_id, reader_id, today.isoformat(), (today + timedelta(days=app.config['LOAN_DAYS'])).isoformat()))
            ident = cursor.lastrowid
            audit('issue', 'loans', ident)
        return jsonify(id=ident), 201

    @app.post('/api/loans/<int:ident>/return')
    @auth(librarian=True)
    def return_book(ident):
        with db():
            db().execute('BEGIN IMMEDIATE')
            loan = db().execute('SELECT * FROM loans WHERE id=?', (ident,)).fetchone()
            if not loan:
                raise APIError('Выдача не найдена.', 404)
            if loan['returned_at']:
                raise APIError('Книга уже возвращена.', 409)
            db().execute('UPDATE loans SET returned_at=? WHERE id=?', (date.today().isoformat(), ident))
            audit('return', 'loans', ident)
        return jsonify(id=ident)

    @app.get('/api/reports')
    @auth(librarian=True)
    def reports():
        def count(query, args=()):
            return db().execute(query, args).fetchone()[0]
        return jsonify(
            books=count('SELECT COUNT(*) FROM books'), copies=count('SELECT COUNT(*) FROM copies'),
            active_loans=count('SELECT COUNT(*) FROM loans WHERE returned_at IS NULL'),
            overdue=count('SELECT COUNT(*) FROM loans WHERE returned_at IS NULL AND due_at<?', (date.today().isoformat(),)),
            popular=[dict(r) for r in db().execute('''SELECT b.id,b.title,COUNT(l.id) AS loan_count FROM books b
                LEFT JOIN copies c ON c.book_id=b.id LEFT JOIN loans l ON l.copy_id=c.id
                GROUP BY b.id ORDER BY loan_count DESC,b.title LIMIT 10''')],
            faculties=[dict(r) for r in db().execute('''SELECT f.id,f.name,COUNT(l.id) AS loan_count FROM faculties f
                LEFT JOIN users u ON u.faculty_id=f.id LEFT JOIN loans l ON l.reader_id=u.id
                GROUP BY f.id ORDER BY f.name''')])

    @app.get('/api/audit')
    @auth(librarian=True)
    def events():
        return jsonify(items=[dict(r) for r in db().execute('''SELECT a.*,u.full_name AS actor FROM audit_events a
            LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT 100''')])

    return app


def seed_demo(app):
    passwords = [os.getenv('DEMO_LIBRARIAN_PASSWORD', ''), os.getenv('DEMO_READER_PASSWORD', '')]
    if any(len(p.strip()) < 10 or len(p.strip()) > 128 for p in passwords):
        raise RuntimeError('В .env задайте DEMO_LIBRARIAN_PASSWORD и DEMO_READER_PASSWORD длиной 10–128 символов.')
    with app.app_context():
        g.app_db = app.config['DATABASE']
        with db():
            if db().execute('SELECT 1 FROM users').fetchone():
                raise RuntimeError('Демонстрационная инициализация разрешена только для пустой базы пользователей.')
            db().executemany('INSERT INTO faculties(name) VALUES(?)', [('Информатика',), ('Филология',), ('Экономика',)])
            db().executemany('INSERT INTO branches(name,address) VALUES(?,?)', [('Центральная библиотека', 'Учебный корпус 1'), ('Научный абонемент', 'Учебный корпус 2')])
            db().executemany('INSERT INTO authors(name) VALUES(?)', [('Михаил Булгаков',), ('Лев Толстой',), ('Александр Пушкин',), ('Фёдор Достоевский',)])
            db().executemany('INSERT INTO books(title,author_id,year,isbn) VALUES(?,?,?,?)', [
                ('Мастер и Маргарита', 1, 2020, 'DEMO-001'), ('Война и мир', 2, 2021, 'DEMO-002'),
                ('Евгений Онегин', 3, 2019, 'DEMO-003'), ('Преступление и наказание', 4, 2022, 'DEMO-004')])
            db().executemany('INSERT INTO copies(book_id,branch_id,inventory_number) VALUES(?,?,?)',
                            [(book, branch, f'LIB-{book:03}-{branch}') for book in range(1, 5) for branch in (1, 2)])
            db().execute("INSERT INTO users(username,password_hash,full_name,role) VALUES(?,?,?,'librarian')",
                         ('librarian', generate_password_hash(passwords[0].strip()), 'Библиотекарь'))
            db().execute("INSERT INTO users(username,password_hash,full_name,role,faculty_id) VALUES(?,?,?,'reader',1)",
                         ('reader', generate_password_hash(passwords[1].strip()), 'Демонстрационный читатель'))


def main():
    parser = argparse.ArgumentParser(description='Библиотека 0.1.0')
    parser.add_argument('command', choices=['run', 'init-demo', 'backup'], nargs='?', default='run')
    parser.add_argument('--output', help='Путь к новой резервной копии SQLite')
    args = parser.parse_args()
    app = create_app()
    if args.command == 'init-demo':
        seed_demo(app)
        print('Демонстрационные данные созданы. Логины: librarian и reader. Пароли — из .env.')
    elif args.command == 'backup':
        if not args.output:
            parser.error('Для backup нужен --output')
        target = Path(args.output).resolve()
        if target.exists():
            parser.error('Файл назначения уже существует. Выберите новый путь.')
        target.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(app.config['DATABASE'])) as source, closing(sqlite3.connect(target)) as dest:
            source.backup(dest)
        print(f'Резервная копия: {target}')
    else:
        app.run(host=os.getenv('HOST', '127.0.0.1'), port=int(os.getenv('PORT', '5000')), debug=False)


if __name__ == '__main__':
    main()
