"""Exercise the public migration, backup and restore command parsers."""

import sqlite3
from contextlib import closing

import pytest

from app import main


def test_cli_migrate_backup_and_restore(tmp_path, monkeypatch):
    live, snapshot, restored = [tmp_path / name for name in ('live.db', 'snapshot.db', 'restored.db')]
    monkeypatch.setenv('DATABASE_PATH', str(live))
    monkeypatch.setattr('sys.argv', ['app.py', 'migrate'])
    main()
    with closing(sqlite3.connect(live)) as conn, conn:
        conn.execute("INSERT INTO authors(name) VALUES('CLI контроль')")
    monkeypatch.setattr('sys.argv', ['app.py', 'backup', '--output', str(snapshot)])
    main()
    with closing(sqlite3.connect(live)) as conn, conn:
        conn.execute('DELETE FROM authors')
    monkeypatch.setattr('sys.argv', ['app.py', 'restore', '--input', str(snapshot), '--output', str(restored)])
    main()
    with closing(sqlite3.connect(restored)) as conn:
        assert conn.execute('SELECT name FROM authors').fetchone()[0] == 'CLI контроль'


@pytest.mark.parametrize('command', ['backup', 'restore'])
def test_cli_requires_explicit_snapshot_arguments(command, monkeypatch):
    monkeypatch.setattr('sys.argv', ['app.py', command])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
