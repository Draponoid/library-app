"""Schema changes must work on empty databases and preserve existing records."""

import sqlite3
from contextlib import closing
from pathlib import Path

from database import migrate


def test_migrate_handles_uri_characters_in_database_path(tmp_path):
    directory = tmp_path / 'lab#3 100%'
    path = directory / 'library.sqlite3'
    migrate(path)
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute('SELECT COUNT(*) FROM _yoyo_migration').fetchone()[0] == 3
        assert conn.execute('SELECT COUNT(*) FROM books').fetchone()[0] == 0


def test_empty_database_and_idempotence(tmp_path):
    path = tmp_path / 'empty.sqlite3'
    migrate(path)
    migrate(path)
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute('SELECT COUNT(*) FROM _yoyo_migration').fetchone()[0] == 3
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
        assert 'renewal_count' in {r[1] for r in conn.execute('PRAGMA table_info(loans)')}


def test_legacy_database_keeps_data(tmp_path):
    path = tmp_path / 'legacy.sqlite3'
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript(Path('tests/fixtures/legacy.sql').read_text(encoding='utf-8'))
        conn.execute("INSERT INTO authors VALUES(41, 'Сохранённый автор')")
        conn.execute("INSERT INTO books VALUES(72, 'Сохранённая книга', 41, 2020, 'LEGACY')")
        conn.execute("INSERT INTO branches VALUES(1, 'Филиал', 'Адрес')")
        conn.execute("INSERT INTO copies VALUES(1, 72, 1, 'INV')")
        conn.execute("INSERT INTO users VALUES(1, 'reader', 'hash', 'Читатель', 'reader', NULL)")
        conn.execute("INSERT INTO loans VALUES(1, 1, 1, '2026-01-01', '2026-01-15', NULL)")
    migrate(path)
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute('SELECT title FROM books WHERE id=72').fetchone()[0] == 'Сохранённая книга'
        assert conn.execute('SELECT due_at, renewal_count FROM loans').fetchone() == ('2026-01-15', 0)
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []


def test_sequential_upgrade_with_data(tmp_path):
    path = tmp_path / 'stages.sqlite3'
    migrate(path, target='0001_initial')
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("INSERT INTO authors(name) VALUES('До обновления')")
        assert 'renewal_count' not in {r[1] for r in conn.execute('PRAGMA table_info(loans)')}
    migrate(path, target='0002_indexes')
    with closing(sqlite3.connect(path)) as conn:
        assert 'one_active_loan_per_copy' in {r[1] for r in conn.execute('PRAGMA index_list(loans)')}
    migrate(path)
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute('SELECT name FROM authors').fetchone()[0] == 'До обновления'
