"""Minimal DB-API bridge for the application's SQLite-shaped queries."""
import re
import psycopg


class Row(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def row_factory(cursor):
    names = [column.name for column in cursor.description]
    return lambda values: Row(zip(names, values))


class InsertResult:
    def __init__(self, ident):
        self.lastrowid = ident


class PostgresConnection:
    def __init__(self, url):
        self.conn = psycopg.connect(url, autocommit=True, row_factory=row_factory)
        self.transaction = None

    def __enter__(self):
        self.transaction = self.conn.transaction()
        self.transaction.__enter__()
        return self

    def __exit__(self, typ, value, tb):
        return self.transaction.__exit__(typ, value, tb)

    def close(self):
        self.conn.close()

    def execute(self, query, params=()):
        if query == 'BEGIN IMMEDIATE':
            return self.conn.execute('SELECT pg_advisory_xact_lock(48210004)')
        query = query.replace('?', '%s')
        # Only these inserts consume lastrowid; RETURNING is per connection and safe under concurrency.
        wants_id = bool(re.match(r'INSERT INTO (users|loans|authors|branches|faculties|books|copies)\b', query, re.I))
        if wants_id:
            cursor = self.conn.execute(query + ' RETURNING id', params)
            return InsertResult(cursor.fetchone()['id'])
        return self.conn.execute(query, params)

    def executemany(self, query, params):
        with self.conn.cursor() as cursor:
            cursor.executemany(query.replace('?', '%s'), params)
