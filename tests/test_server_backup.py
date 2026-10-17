"""Exercise backup publication and cleanup with real failing child programs."""

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    'server_backup', Path(__file__).resolve().parents[1] / 'deploy' / 'postgres_backup.py'
)
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)


@pytest.fixture
def native_tools(tmp_path, monkeypatch):
    previous_umask = os.umask(0o077)
    tools = tmp_path / 'tools'
    tools.mkdir()
    (tools / 'pg_dump.py').write_text(
        'import os, sys\n'
        "assert os.environ.get('PGPASSWORD') == 'unit-test-secret'\n"
        "assert 'unit-test-secret' not in ' '.join(sys.argv)\n"
        "sys.stdout.write('PGDMP fake archive')\n"
        "sys.exit(int(os.environ.get('FAKE_DUMP_FAILURE', '0')))\n"
    )
    (tools / 'pg_restore.py').write_text(
        'import os, sys\n'
        "assert '--list' in sys.argv\n"
        "assert sys.stdin.read() == 'PGDMP fake archive'\n"
        "sys.exit(int(os.environ.get('FAKE_RESTORE_FAILURE', '0')))\n"
    )
    monkeypatch.setenv('DB_PASSWORD', 'unit-test-secret')
    monkeypatch.delenv('PGPASSWORD', raising=False)
    monkeypatch.setattr(backup, 'command', lambda name, args, env: [sys.executable, str(tools / f'{name}.py'), *args])
    yield tmp_path / 'backups'
    os.umask(previous_umask)


def test_success_publishes_archive_and_retains_only_matching_complete_copies(native_tools):
    native_tools.mkdir()
    for day in range(1, 10):
        (native_tools / f'library-db-202601{day:02}T000000000000Z.dump').write_text('old archive')
    unrelated = native_tools / 'somebody-else.dump'
    unrelated.write_text('do not delete')
    incomplete = native_tools / 'library-db-20260101T000000000000Z.dump.partial'
    incomplete.write_text('old partial')
    target = backup.backup(native_tools, 'library', 'library-db')
    assert target.read_text() == 'PGDMP fake archive'
    assert len(list(native_tools.glob('library-db-*.dump'))) == 7
    assert not (native_tools / 'library-db-20260101T000000000000Z.dump').exists()
    assert unrelated.read_text() == 'do not delete'
    assert incomplete.exists()
    assert not target.with_suffix('.dump.partial').exists()


@pytest.mark.parametrize('failed_program', ['FAKE_DUMP_FAILURE', 'FAKE_RESTORE_FAILURE'])
def test_failed_dump_or_archive_validation_preserves_old_backups(native_tools, monkeypatch, failed_program):
    native_tools.mkdir()
    existing = native_tools / 'library-db-20260101T000000000000Z.dump'
    existing.write_text('known good')
    monkeypatch.setenv(failed_program, '23')
    with pytest.raises(RuntimeError, match='failed'):
        backup.backup(native_tools, 'library', 'library-db', keep=1)
    assert existing.read_text() == 'known good'
    assert list(native_tools.glob('*.dump')) == [existing]
    assert not list(native_tools.glob('*.partial'))


def test_bad_prefix_never_creates_output(native_tools):
    with pytest.raises(ValueError, match='prefix'):
        backup.backup(native_tools, 'library', '../outside')
    assert not native_tools.exists()


def test_lock_prevents_a_second_backup(native_tools):
    native_tools.mkdir()
    with (native_tools / '.library-db.lock').open('a+') as lock:
        backup.acquire_lock(lock)
        with pytest.raises(RuntimeError, match='already running'):
            backup.backup(native_tools, 'library', 'library-db')
    assert not list(native_tools.glob('*.dump'))


@pytest.mark.parametrize('suffix', ['.dump', '.dump.partial'])
def test_timestamp_collision_never_overwrites_or_removes_existing_file(native_tools, monkeypatch, suffix):
    class FrozenDatetime(backup.dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 1, 1, tzinfo=tz)

    monkeypatch.setattr(backup.dt, 'datetime', FrozenDatetime)
    native_tools.mkdir()
    existing = native_tools / ('library-db-20260101T000000000000Z' + suffix)
    existing.write_text('preserve this exact file')
    with pytest.raises(FileExistsError):
        backup.backup(native_tools, 'library', 'library-db')
    assert existing.read_text() == 'preserve this exact file'


def test_existing_libpq_variables_take_precedence(monkeypatch):
    monkeypatch.setenv('DB_HOST', 'application-db')
    monkeypatch.setenv('PGHOST', 'maintenance-db')
    monkeypatch.setenv('DB_PASSWORD', 'app-password')
    monkeypatch.setenv('PGPASSWORD', 'maintenance-password')
    env = backup.connection_environment()
    assert env['PGHOST'] == 'maintenance-db'
    assert env['PGPASSWORD'] == 'maintenance-password'


@pytest.mark.parametrize(
    'diagnostic, label',
    [
        ('failed to get data for sequence "private-name"; password=do-not-log', 'sequence SELECT privilege missing'),
        ('permission denied for table private-table; password=do-not-log', 'database permission denied'),
    ],
)
def test_dump_failure_classification_never_exposes_diagnostics(tmp_path, monkeypatch, diagnostic, label):
    tool = tmp_path / 'failed_dump.py'
    tool.write_text(f'import sys; print({diagnostic!r}, file=sys.stderr); sys.exit(1)')
    monkeypatch.setattr(backup, 'command', lambda name, args, env: [sys.executable, str(tool), *args])
    with pytest.raises(RuntimeError, match=label) as error:
        backup.dump_archive(tmp_path / 'failed.partial', 'library', {})
    assert 'do-not-log' not in str(error.value)
    assert 'private-' not in str(error.value)


def test_restore_check_refuses_a_remote_server():
    with pytest.raises(RuntimeError, match='local PostgreSQL socket'):
        backup.restore_check(Path('unused'), {}, {'PGHOST': '192.168.204.21'})


@pytest.mark.parametrize('option, value', [('--prefix', '../outside'), ('--keep', '0')])
def test_cli_reports_invalid_request_without_creating_files(native_tools, monkeypatch, capsys, option, value):
    monkeypatch.setattr(sys, 'argv', ['backup', '--output-directory', str(native_tools), option, value])
    assert backup.main() == 1
    assert 'Backup failed' in capsys.readouterr().err
    assert not native_tools.exists()


def test_cli_success_returns_zero_and_publishes(native_tools, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['backup', '--output-directory', str(native_tools)])
    assert backup.main() == 0
    assert len(list(native_tools.glob('library-db-*.dump'))) == 1


def test_missing_postgresql_client_fails_clearly(monkeypatch):
    monkeypatch.setattr(backup.shutil, 'which', lambda _: None)
    with pytest.raises(RuntimeError, match='unavailable: pg_dump'):
        backup.binary('pg_dump')


def test_subprocess_diagnostic_never_exposes_password(tmp_path, monkeypatch):
    tool = tmp_path / 'failure.py'
    tool.write_text("import sys; print('password=do-not-log', file=sys.stderr); sys.exit(19)")
    monkeypatch.setattr(backup, 'command', lambda *_: [sys.executable, str(tool)])
    with pytest.raises(RuntimeError, match='pg_dump failed') as error:
        backup.run('pg_dump')
    assert 'do-not-log' not in str(error.value)


@pytest.mark.parametrize('failure', ['', 'createdb', 'pg_restore', 'counts'])
def test_restore_validation_cleans_only_its_generated_database(tmp_path, monkeypatch, failure):
    archive = tmp_path / 'archive.dump'
    archive.write_text('custom archive')
    log = tmp_path / 'commands.jsonl'
    expected = {'counts': {'books': 12}, 'controls': {'books': 'test-control'}}
    tool = tmp_path / 'restore_tool.py'
    tool.write_text(
        'import json, os, sys\n'
        'name, args = sys.argv[1], sys.argv[2:]\n'
        "with open(os.environ['TEST_LOG'], 'a') as log: log.write(json.dumps([name, args]) + '\\n')\n"
        "if name == os.environ['TEST_FAILURE']: sys.exit(17)\n"
        "if name == 'pg_restore': assert sys.stdin.read() == 'custom archive'\n"
        "if name == 'psql': print(os.environ['TEST_COUNTS'])\n"
    )
    monkeypatch.setattr(backup, 'command', lambda name, args, env: [sys.executable, str(tool), name, *args])
    env = os.environ.copy()
    env.update(
        PGHOST='/local/test/socket',
        PGUSER='local_test_admin',
        TEST_LOG=str(log),
        TEST_FAILURE=failure,
        TEST_COUNTS=json.dumps({} if failure == 'counts' else expected),
    )
    if failure:
        with pytest.raises(RuntimeError):
            backup.restore_check(archive, expected, env)
    else:
        backup.restore_check(archive, expected, env)
    commands = [json.loads(line) for line in log.read_text().splitlines()]
    generated = commands[0][1][-1]
    assert generated.startswith('library_restore_check_')
    assert generated != 'library'
    if failure == 'createdb':
        assert [name for name, _ in commands] == ['createdb']
    else:
        assert commands[-1] == ['dropdb', ['--maintenance-db=postgres', generated]]
        restore_args = next(args for name, args in commands if name == 'pg_restore')
        assert '--exit-on-error' in restore_args and '--single-transaction' in restore_args
        assert restore_args[restore_args.index('--dbname') + 1] == generated
    assert archive.read_text() == 'custom archive'


@pytest.mark.parametrize('snapshot', ['00000003-0000001A-1', 'invalid-snapshot'])
def test_exported_snapshot_keeps_source_transaction_open(tmp_path, monkeypatch, snapshot):
    protocol = tmp_path / 'protocol.txt'
    script = tmp_path / 'psql.py'
    script.write_text(
        'import json, sys\n'
        'request = sys.stdin.readline()\n'
        'print(sys.argv[1], flush=True)\n'
        "if sys.argv[1] == 'invalid-snapshot': sys.stdin.read(); sys.exit(0)\n"
        'controls = sys.stdin.readline()\n'
        "print(json.dumps({'counts': {'books': 12}}), flush=True)\n"
        'end = sys.stdin.readline()\n'
        "with open(sys.argv[2], 'w') as f: f.write(request + controls + end)\n"
    )
    monkeypatch.setattr(backup, 'command', lambda *_: [sys.executable, str(script), snapshot, str(protocol)])
    if snapshot == 'invalid-snapshot':
        with pytest.raises(RuntimeError, match='consistent PostgreSQL snapshot'):
            with backup.exported_snapshot('library', os.environ.copy()):
                pytest.fail('An invalid snapshot must not be used')
    else:
        with backup.exported_snapshot('library', os.environ.copy()) as (actual, controls):
            assert actual == snapshot
            assert controls == {'counts': {'books': 12}}
            assert not protocol.exists()
        request = protocol.read_text()
        assert request.startswith('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SELECT pg_export_snapshot();')
        assert 'count(*) FROM public.books' in request
        assert request.endswith('ROLLBACK;\n')
