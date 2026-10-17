"""Exercise the actual snapshot and recovery operations on disposable data."""

import sqlite3
from contextlib import closing

import pytest

from database import backup_database, migrate, restore_database


def test_restore_after_deliberate_delete(tmp_path):
    live, backup, restored = [tmp_path / name for name in ('live.db', 'backup.db', 'restored.db')]
    migrate(live)
    with closing(sqlite3.connect(live)) as conn, conn:
        conn.execute("INSERT INTO authors(name) VALUES('Контрольная запись')")
    backup_database(live, backup)
    with closing(sqlite3.connect(live)) as conn, conn:
        conn.execute('DELETE FROM authors')
        assert conn.execute('SELECT COUNT(*) FROM authors').fetchone()[0] == 0
    restore_database(backup, restored)
    with closing(sqlite3.connect(restored)) as conn:
        assert conn.execute('SELECT name FROM authors').fetchone()[0] == 'Контрольная запись'
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []


@pytest.mark.parametrize('operation', [backup_database, restore_database])
def test_never_overwrite_existing_file(tmp_path, operation):
    source, target = tmp_path / 'source.db', tmp_path / 'valuable.txt'
    migrate(source)
    target.write_bytes(b'keep me')
    with pytest.raises(FileExistsError):
        operation(source, target)
    assert target.read_bytes() == b'keep me'


@pytest.mark.parametrize('operation', [backup_database, restore_database])
def test_missing_or_corrupt_source_creates_no_target(tmp_path, operation):
    source, target = tmp_path / 'missing.db', tmp_path / 'target.db'
    with pytest.raises((FileNotFoundError, sqlite3.DatabaseError, ValueError)):
        operation(source, target)
    assert not target.exists()
    source.write_bytes(b'this is not SQLite')
    with pytest.raises((sqlite3.DatabaseError, ValueError)):
        operation(source, target)
    assert not target.exists()


def test_snapshot_includes_uncheckpointed_wal(tmp_path):
    source, target = tmp_path / 'wal.db', tmp_path / 'backup.db'
    migrate(source)
    with closing(sqlite3.connect(source)) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute("INSERT INTO authors(name) VALUES('Из WAL')")
        conn.commit()
        backup_database(source, target)
    with closing(sqlite3.connect(target)) as conn:
        assert conn.execute('SELECT name FROM authors').fetchone()[0] == 'Из WAL'
