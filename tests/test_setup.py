import sqlite3
from contextlib import closing
from pathlib import Path

from setup_local import configure


def test_initial_setup_and_repeat_preserve_secrets_and_data(tmp_path):
    (tmp_path / '.env.example').write_text(Path('.env.example').read_text(encoding='utf-8'), encoding='utf-8')
    configure(tmp_path)
    first = (tmp_path / '.env').read_bytes()
    assert b'replace-with-' not in first
    with closing(sqlite3.connect(tmp_path / 'data/library.sqlite3')) as conn, conn:
        assert conn.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 2
        conn.execute("UPDATE books SET title='Своё название' WHERE id=1")
    configure(tmp_path)
    assert (tmp_path / '.env').read_bytes() == first
    with closing(sqlite3.connect(tmp_path / 'data/library.sqlite3')) as conn:
        assert conn.execute('SELECT title FROM books WHERE id=1').fetchone()[0] == 'Своё название'


def test_setup_honors_exported_database_path(tmp_path, monkeypatch):
    (tmp_path / '.env.example').write_text(Path('.env.example').read_text(encoding='utf-8'), encoding='utf-8')
    database = tmp_path / 'custom.db'
    monkeypatch.setenv('DATABASE_PATH', str(database))
    configure(tmp_path)
    assert database.is_file()
    assert not (tmp_path / 'data/library.sqlite3').exists()
