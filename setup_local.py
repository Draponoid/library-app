"""One-command bootstrap: isolated dependencies, secrets, migrations and demo data."""

import argparse
import os
import secrets
import sqlite3
import subprocess  # nosec B404 # - fixed local Python commands, never a shell.
import venv
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def configure(root=ROOT):
    from dotenv import dotenv_values

    from app import create_app, seed_demo

    env = root / '.env'
    if not env.exists():
        text = (root / '.env.example').read_text(encoding='utf-8')
        text = text.replace('replace-with-a-random-string-at-least-32-characters', secrets.token_hex(32))
        text = text.replace('ChangeMe-Library-2026!', secrets.token_urlsafe(18))
        text = text.replace('ChangeMe-Reader-2026!', secrets.token_urlsafe(18))
        with env.open('x', encoding='utf-8') as file:
            file.write(text)
    values = {**dotenv_values(env), **os.environ}
    path = root / values.get('DATABASE_PATH', 'data/library.sqlite3')
    app = create_app({'SECRET_KEY': values.get('SECRET_KEY'), 'DATABASE': str(path)})
    with closing(sqlite3.connect(path)) as conn:
        empty = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0] == 0
    if empty:
        original = {key: os.environ.get(key) for key in ('DEMO_LIBRARIAN_PASSWORD', 'DEMO_READER_PASSWORD')}
        try:
            for key in original:
                os.environ[key] = values.get(key, '')
            seed_demo(app)
        finally:
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    print('Готово. Учётные данные находятся в .env. Запуск: make run')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configure', action='store_true')
    args = parser.parse_args()
    if args.configure:
        configure()
        return
    executable = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not executable.is_file():
        venv.EnvBuilder(with_pip=True).create(ROOT / '.venv')
    subprocess.run(  # nosec B603 # - absolute venv interpreter, fixed pip arguments, shell=False.
        [str(executable), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements-lock.txt')],
        check=True,
        cwd=ROOT,
    )
    subprocess.run(  # nosec B603 # - absolute local script and interpreter, no user command input.
        [str(executable), str(ROOT / 'setup_local.py'), '--configure'],
        check=True,
        cwd=ROOT,
    )


if __name__ == '__main__':
    main()
