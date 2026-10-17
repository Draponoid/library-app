#!/usr/bin/env python3
"""Atomic PostgreSQL backups; credentials come only from the process environment."""

import argparse
import contextlib
import datetime as dt
import json
import os
import re
import shutil
import subprocess  # nosec B404 # - Argument arrays throughout; no shell is involved.
import sys
import uuid
from pathlib import Path

TABLES = ('authors', 'books', 'branches', 'copies', 'faculties', 'users', 'loans', 'sessions', 'audit_events')


def binary(name):
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f'Required PostgreSQL program is unavailable: {name}')
    return path


def command(name, args, env):
    argv = [binary(name), *args]
    if env and env.get('LIBRARY_BACKUP_AS_POSTGRES') == '1':
        argv = [binary('runuser'), '-u', 'postgres', '--', *argv]
    return argv


def run(name, *args, env=None, input_path=None):
    with contextlib.ExitStack() as stack:
        source = stack.enter_context(Path(input_path).open('rb')) if input_path else None
        result = subprocess.run(  # nosec B603 # - Fixed PostgreSQL tools, absolute executable paths, argument arrays without shell.
            command(name, args, env), env=env, stdin=source, capture_output=True, text=True, check=False
        )
    if result.returncode:
        # PostgreSQL diagnostics may contain connection strings; keep them out of journald.
        raise RuntimeError(f'{name} failed (exit {result.returncode}); no backup was published')
    return result.stdout.strip()


def connection_environment():
    env = os.environ.copy()
    for old, new in (
        ('DB_HOST', 'PGHOST'),
        ('DB_PORT', 'PGPORT'),
        ('DB_NAME', 'PGDATABASE'),
        ('DB_USER', 'PGUSER'),
        ('DB_PASSWORD', 'PGPASSWORD'),
    ):
        if old in env and new not in env:
            env[new] = env[old]
    env.setdefault('PGCONNECT_TIMEOUT', '15')
    return env


def controls_sql():
    # Only the constant table allowlists below are interpolated, never user input.
    counts = ', '.join(f"'{table}', (SELECT count(*) FROM public.{table})" for table in TABLES)  # nosec B608 # - Table identifiers come only from the constant TABLES allowlist.
    controls = ', '.join(
        f"'{table}', (SELECT md5(row_to_json(t)::text) FROM public.{table} t ORDER BY id LIMIT 1)"  # nosec B608 # - Table identifiers come only from the constant TABLES allowlist.
        for table in ('books', 'users', 'branches')
    )
    return (
        f"SELECT json_build_object('counts', json_build_object({counts}), 'controls', json_build_object({controls}));"
    )


@contextlib.contextmanager
def exported_snapshot(database, env):
    proc = subprocess.Popen(  # nosec B603 # - Fixed PostgreSQL tools, absolute executable paths, argument arrays without shell.
        command(
            'psql',
            ['--no-psqlrc', '--tuples-only', '--no-align', '--quiet', '--set', 'ON_ERROR_STOP=1', '--dbname', database],
            env,
        ),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
    )
    try:
        proc.stdin.write('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SELECT pg_export_snapshot();\n')
        proc.stdin.flush()
        snapshot = proc.stdout.readline().strip()
        if not re.fullmatch(r'[0-9A-Fa-f]+-[0-9A-Fa-f]+-[0-9]+', snapshot):
            raise RuntimeError('Could not export a consistent PostgreSQL snapshot')
        proc.stdin.write(controls_sql() + '\n')
        proc.stdin.flush()
        expected = json.loads(proc.stdout.readline())
        yield snapshot, expected
        proc.stdin.write('ROLLBACK;\n')
        proc.stdin.flush()
    finally:
        if proc.stdin:
            proc.stdin.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        if proc.stdout:
            proc.stdout.close()


def restore_check(archive, expected, env):
    name = (
        'library_restore_check_'
        + dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d%H%M%S')
        + '_'
        + uuid.uuid4().hex[:8]
    )
    # Keep this maintenance action on a local socket; CREATE DATABASE requires an admin role.
    if env.get('PGHOST') and not env['PGHOST'].startswith('/'):
        raise RuntimeError('Restore validation requires local PostgreSQL socket authentication')
    created = False
    try:
        run('createdb', '--maintenance-db=postgres', '--template=template0', name, env=env)
        created = True
        run(
            'pg_restore',
            '--exit-on-error',
            '--single-transaction',
            '--no-owner',
            '--no-privileges',
            '--dbname',
            name,
            env=env,
            input_path=archive,
        )
        actual = json.loads(
            run(
                'psql',
                '--no-psqlrc',
                '--tuples-only',
                '--no-align',
                '--set',
                'ON_ERROR_STOP=1',
                '--dbname',
                name,
                '--command',
                controls_sql(),
                env=env,
            )
        )
        if actual != expected:
            raise RuntimeError('Restored table counts or control-record hashes differ from the source snapshot')
        print('Restore validation passed: table counts and control-record hashes match the source snapshot', flush=True)
    finally:
        if created:
            if not re.fullmatch(r'library_restore_check_[0-9]{14}_[0-9a-f]{8}', name):
                raise RuntimeError('Refusing cleanup of an unexpected database name')
            run('dropdb', '--maintenance-db=postgres', name, env=env)


def dump_archive(path, database, env, snapshot=None):
    args = ['--format=custom', '--dbname', database]
    if snapshot:
        args.extend(['--snapshot', snapshot])
    tool_env = {**env, 'LC_ALL': 'C'}
    with path.open('wb') as archive:
        result = subprocess.run(  # nosec B603 # - Fixed PostgreSQL tools, absolute executable paths, argument arrays without shell.
            command('pg_dump', args, tool_env), env=tool_env, stdout=archive, stderr=subprocess.PIPE, check=False
        )
    if result.returncode:
        # Classify known diagnostics using fixed labels; never print raw stderr or credentials.
        error = result.stderr.decode('utf-8', errors='replace').lower()
        reason = 'unclassified error'
        for phrase, label in (
            ('failed to get data for sequence', 'sequence SELECT privilege missing or sequence dropped'),
            ('permission denied', 'database permission denied'),
            ('no password supplied', 'database password missing'),
            ('password authentication failed', 'database password rejected'),
            ('connection refused', 'database connection refused'),
            ('no pg_hba.conf entry', 'database connection rejected by pg_hba'),
            ('version mismatch', 'PostgreSQL version mismatch'),
        ):
            if phrase in error:
                reason = label
                break
        raise RuntimeError(f'pg_dump failed (exit {result.returncode}; {reason}); no backup was published')


def acquire_lock(lock):
    try:
        if os.name == 'nt':
            import msvcrt

            lock.seek(0)
            if not lock.read(1):
                lock.write('0')
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise RuntimeError('Another backup with this prefix is already running') from None


def backup(directory, database, prefix, keep=7, validate=False, as_postgres=False):
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', prefix):
        raise ValueError('Invalid backup filename prefix')
    if keep < 1:
        raise ValueError('Retention must keep at least one copy')
    os.umask(0o077)
    if Path(directory).is_symlink():
        raise ValueError('Backup directory must not be a symlink')
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    # OS file locks release automatically on a killed or failed process.
    with (directory / f'.{prefix}.lock').open('a+') as lock:
        acquire_lock(lock)
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        target = directory / f'{prefix}-{stamp}.dump'
        partial = target.with_suffix('.dump.partial')
        if target.exists():
            raise FileExistsError('A backup with this timestamp already exists')
        env = connection_environment()
        if as_postgres:
            if os.geteuid() != 0 or env.get('PGHOST') or env.get('PGUSER', 'postgres') != 'postgres':
                raise RuntimeError('--as-postgres requires root and local postgres socket authentication')
            env['LIBRARY_BACKUP_AS_POSTGRES'] = '1'
        created_partial = False
        try:
            with partial.open('xb'):
                pass
            created_partial = True
            if validate:
                with exported_snapshot(database, env) as (snapshot, expected):
                    dump_archive(partial, database, env, snapshot)
                restore_check(partial, expected, env)
            else:
                dump_archive(partial, database, env)
            if partial.stat().st_size == 0:
                raise RuntimeError('pg_dump produced an empty archive')
            run('pg_restore', '--list', env=env, input_path=partial)
            with partial.open('r+b') as archive:
                os.fsync(archive.fileno())
            partial.replace(target)
            pattern = re.compile(re.escape(prefix) + r'-[0-9]{8}T[0-9]{12}Z\.dump')
            archives = sorted(
                p for p in directory.iterdir() if pattern.fullmatch(p.name) and p.is_file() and not p.is_symlink()
            )
            for obsolete in archives[:-keep]:
                obsolete.unlink()
            print(f'Backup complete: {target.name}; retained at most {keep} successful copies', flush=True)
            return target
        finally:
            if created_partial:
                partial.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', required=True)
    parser.add_argument('--database', default=os.environ.get('PGDATABASE', os.environ.get('DB_NAME', 'library')))
    parser.add_argument('--prefix', default='library-db')
    parser.add_argument('--keep', type=int, default=7)
    parser.add_argument('--validate-restore', action='store_true')
    parser.add_argument(
        '--as-postgres', action='store_true', help='Root opens protected files; PostgreSQL tools run as postgres'
    )
    args = parser.parse_args()
    try:
        backup(args.output_directory, args.database, args.prefix, args.keep, args.validate_restore, args.as_postgres)
    except (OSError, RuntimeError, ValueError) as error:
        print(f'Backup failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
