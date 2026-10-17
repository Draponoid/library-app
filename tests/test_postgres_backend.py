"""Backend selection stays explicit in tests and never migrates as the runtime role."""

import sqlite3
from urllib.parse import parse_qs, urlsplit

import pytest
from test_config import TEST_CONFIG

import app as application
import database


def test_shared_connector_preserves_sqlite_transactions_and_named_rows(tmp_path):
    assert hasattr(database, 'connect_database'), 'a shared backend connector is required'
    conn = database.connect_database(tmp_path / 'library.sqlite3')
    try:
        conn.execute('CREATE TABLE sample(id INTEGER PRIMARY KEY, name TEXT)')
        with conn:
            row = conn.execute('INSERT INTO sample(name) VALUES(?) RETURNING id', ('sample',)).fetchone()
        assert row['id'] == row[0] == 1
        with pytest.raises(ValueError), conn:
            conn.execute('INSERT INTO sample(name) VALUES(?)', ('rolled back',))
            raise ValueError('rollback')
        assert conn.execute('SELECT COUNT(*) FROM sample').fetchone()[0] == 1
        assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    finally:
        conn.close()


def test_explicit_postgres_startup_never_initializes_sqlite(tmp_path):
    path = tmp_path / 'must-not-exist.sqlite3'
    instance = application.create_app({**TEST_CONFIG, 'DATABASE': str(path), 'POSTGRES': {'host': '127.0.0.1'}})
    assert not path.exists(), 'PostgreSQL startup must not initialize an unrelated SQLite database'
    assert instance.config['POSTGRES']['host'] == '127.0.0.1'


def test_empty_postgres_configuration_never_falls_back_to_sqlite(monkeypatch, tmp_path):
    import psycopg

    def unavailable(**kwargs):
        raise psycopg.OperationalError('default PostgreSQL is unavailable')

    monkeypatch.setattr(database.psycopg, 'connect', unavailable)
    path = tmp_path / 'must-not-create.sqlite3'
    instance = application.create_app({**TEST_CONFIG, 'DATABASE': str(path), 'POSTGRES': {}})
    assert instance.test_client().get('/health').status_code == 503
    assert not path.exists()


def test_postgres_environment_is_ignored_by_sqlite_tests(monkeypatch, tmp_path):
    monkeypatch.setenv('DB_HOST', 'must-not-connect.invalid')
    path = tmp_path / 'isolated.sqlite3'
    instance = application.create_app({**TEST_CONFIG, 'DATABASE': str(path)})
    assert instance.config.get('POSTGRES') is None
    assert instance.test_client().get('/health').status_code == 200


def test_postgres_environment_selects_backend_without_connecting(monkeypatch, tmp_path):
    monkeypatch.setenv('DB_HOST', '127.0.0.1')
    monkeypatch.setenv('DB_PORT', '65432')
    monkeypatch.setenv('DB_NAME', 'library')
    monkeypatch.setenv('DB_USER', 'labapp')
    monkeypatch.setenv('DB_PASSWORD', 'private-password')
    path = tmp_path / 'unused.sqlite3'
    instance = application.create_app({**TEST_CONFIG, 'TESTING': False, 'DATABASE': str(path)})
    assert not path.exists()
    assert instance.config['POSTGRES']['port'] == 65432
    response = instance.test_client().get('/health')
    assert response.status_code == 503
    assert 'private-password' not in response.get_data(as_text=True)


@pytest.mark.parametrize('error_name,status', [('IntegrityError', 409), ('InterfaceError', 503)])
def test_postgres_errors_keep_public_http_contract(monkeypatch, tmp_path, error_name, status):
    import psycopg

    instance = application.create_app({**TEST_CONFIG, 'DATABASE': str(tmp_path / 'errors.sqlite3')})

    def unavailable():
        raise getattr(psycopg, error_name)('private connection details')

    monkeypatch.setattr(application, 'db', unavailable)
    response = instance.test_client().get('/health')
    assert response.status_code == status
    assert 'private connection details' not in response.get_data(as_text=True)


def test_postgres_migration_rejects_unknown_target_before_connecting():
    assert hasattr(database, 'migrate_postgres'), 'admin-only PostgreSQL migrations are required'
    with pytest.raises(ValueError, match='Unknown migration'):
        database.migrate_postgres({'host': 'must-not-connect.invalid'}, target='missing')


def test_postgres_migration_rejects_invalid_schema_before_connecting():
    assert hasattr(database, 'migrate_postgres'), 'admin-only PostgreSQL migrations are required'
    with pytest.raises(ValueError, match='schema'):
        database.migrate_postgres({}, schema='public,other')


@pytest.mark.parametrize('host', ['/var/run/postgresql', '127.0.0.1', '::1'])
def test_postgres_migration_uri_preserves_socket_paths_and_special_credentials(host):
    assert hasattr(database, 'postgres_migration_uri'), 'migration connection parameters need URI encoding'
    config = {'host': host, 'port': 5432, 'dbname': 'library', 'user': 'migration user', 'password': 'p@ss:/?# %'}
    parsed = urlsplit(database.postgres_migration_uri(config, 'public'))
    params = parse_qs(parsed.query)
    assert parsed.scheme == 'postgresql+psycopg'
    assert parsed.hostname is None
    assert params['host'] == [host]
    assert params['password'] == ['p@ss:/?# %']
    assert params['user'] == ['migration user']
    assert params['dbname'] == ['library']
    assert params['options'] == ['-csearch_path=public']
    assert 'options' not in config


def test_postgres_migration_failure_does_not_expose_credentials(monkeypatch):
    def fail(uri):
        raise RuntimeError(uri)

    monkeypatch.setattr(database, 'get_backend', fail)
    with pytest.raises(RuntimeError) as failure:
        database.migrate_postgres({'password': 'must-remain-private'})
    assert 'must-remain-private' not in str(failure.value)
    assert failure.value.__suppress_context__


def test_connector_retains_sqlite_integrity_errors(tmp_path):
    assert hasattr(database, 'connect_database'), 'a shared backend connector is required'
    conn = database.connect_database(tmp_path / 'constraints.sqlite3')
    try:
        conn.execute('CREATE TABLE parent(id INTEGER PRIMARY KEY)')
        conn.execute('CREATE TABLE child(parent_id INTEGER REFERENCES parent(id))')
        with pytest.raises(sqlite3.IntegrityError), conn:
            conn.execute('INSERT INTO child VALUES(?)', (999,))
    finally:
        conn.close()
