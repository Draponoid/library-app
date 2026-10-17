"""Shared database connections, admin migrations and SQLite snapshots."""

import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import quote, urlencode

import psycopg
from psycopg.rows import dict_row
from yoyo import get_backend, read_migrations

ROOT = Path(__file__).resolve().parent


def postgres_config():
    """Use the existing service EnvironmentFile without putting credentials in a DSN."""
    if not os.getenv('DB_HOST'):
        return None
    return {
        'host': os.environ['DB_HOST'],
        'port': int(os.getenv('DB_PORT', '5432')),
        'dbname': os.getenv('DB_NAME', 'library'),
        'user': os.getenv('DB_USER', 'labapp'),
        'password': os.getenv('DB_PASSWORD', ''),
        'connect_timeout': 5,
        'application_name': 'library-lab3',
    }


class PostgresConnection:
    """Keep the application's SQLite transaction boundary on PostgreSQL."""

    def __init__(self, config):
        self.connection = psycopg.connect(**config, autocommit=True, row_factory=dict_row)

    def __enter__(self):
        self.transaction = self.connection.transaction()
        self.transaction.__enter__()
        return self

    def __exit__(self, *exception):
        return self.transaction.__exit__(*exception)

    def execute(self, query, params=()):
        if query == 'BEGIN IMMEDIATE':
            # Share the deployed Lab 2 lock during the upgrade as well.
            return self.connection.execute('SELECT pg_advisory_xact_lock(20261003)')
        # Application SQL uses static statements; user data always stays in params.
        return self.connection.execute(query.replace('?', '%s'), params)

    def executemany(self, query, params):
        with self.connection.cursor() as cursor:
            cursor.executemany(query.replace('?', '%s'), params)

    def close(self):
        self.connection.close()


def connect_database(target):
    if isinstance(target, dict):
        return PostgresConnection(target)
    conn = sqlite3.connect(target, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def postgres_migration_uri(config, schema):
    # Query parameters also support Unix sockets and reserved credential characters.
    params = {**config, 'options': f'-csearch_path={schema}'}
    return 'postgresql+psycopg:///?' + urlencode(params)


def migrate_postgres(config, target=None, schema='public'):
    """Run as the database administrator; the application role never runs DDL."""
    if not re.fullmatch(r'[a-z_][a-z0-9_]*', schema):
        raise ValueError('Invalid PostgreSQL schema')
    migrations = read_migrations(str(ROOT / 'migrations' / 'postgresql'))
    if target is not None:
        ids = [migration.id for migration in migrations]
        if target not in ids:
            raise ValueError('Unknown migration: ' + target)
        migrations = migrations[: ids.index(target) + 1]
    uri = postgres_migration_uri(config, schema)
    try:
        with get_backend(uri) as backend:
            with backend.lock():
                backend.apply_migrations(backend.to_apply(migrations))
    except Exception:
        # Driver and migration exceptions can include the credential-bearing URI.
        raise RuntimeError('PostgreSQL migrations failed; check database connectivity and admin permissions.') from None


def migrate(path, target=None):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    migrations = read_migrations(str(ROOT / 'migrations'))
    if target is not None:
        ids = [m.id for m in migrations]
        if target not in ids:
            raise ValueError('Unknown migration: ' + target)
        migrations = migrations[: ids.index(target) + 1]
    with get_backend('sqlite:///' + quote(path.as_posix(), safe='/:')) as backend:
        with backend.lock():
            backend.apply_migrations(backend.to_apply(migrations))
    with closing(sqlite3.connect(path)) as conn:
        conn.execute('PRAGMA journal_mode=WAL')


def validate_database(conn):
    if conn.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
        raise ValueError('SQLite integrity_check failed')
    if conn.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('SQLite foreign_key_check failed')
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required = {'books', 'authors', 'branches', 'copies', 'users', 'loans', 'faculties', 'sessions', 'audit_events'}
    if not required <= tables:
        raise ValueError('Not a library database')


def backup_database(source, target):
    source, target = Path(source).resolve(), Path(target).resolve()
    if target.exists():
        raise FileExistsError(target)
    if not source.is_file():
        raise FileNotFoundError(source)
    # A read-only connection also prevents accidentally creating an empty source.
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as origin:
        validate_database(origin)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb'):
            pass
        try:
            with closing(sqlite3.connect(target)) as snapshot:
                origin.backup(snapshot)
                validate_database(snapshot)
        except Exception:
            target.unlink(missing_ok=True)
            raise
    return target


def restore_database(source, target):
    """Restore to a NEW file; stop the app before switching DATABASE_PATH to it."""
    return backup_database(source, target)
