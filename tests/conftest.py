"""Keep legacy unittest fixtures and pytest fixtures inside the project sandbox."""

import os
import socket
import tempfile
from pathlib import Path

import pytest


def pytest_configure():
    directory = Path(__file__).resolve().parents[1] / '.tmp'
    directory.mkdir(exist_ok=True)
    tempfile.tempdir = str(directory)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    # Yoyo logs the hostname; tests must not wait for external reverse DNS.
    monkeypatch.setattr(socket, 'getfqdn', lambda _name='': socket.gethostname())
    for name in (
        'SECRET_KEY',
        'DATABASE_PATH',
        'SESSION_HOURS',
        'LOAN_DAYS',
        'MAX_ACTIVE_LOANS',
        'COOKIE_SECURE',
        'DEMO_LIBRARIAN_PASSWORD',
        'DEMO_READER_PASSWORD',
        'DB_HOST',
        'DB_PORT',
        'DB_NAME',
        'DB_USER',
        'DB_PASSWORD',
        'LABAPP_ENV_FILE',
        'PGHOST',
        'PGPORT',
        'PGDATABASE',
        'PGUSER',
        'PGPASSWORD',
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('DEMO_LIBRARIAN_PASSWORD', 'Test-Library-2026!')
    monkeypatch.setenv('DEMO_READER_PASSWORD', 'Test-Reader-2026!')
    # unittest fixtures also change os.environ directly; monkeypatch restores them.
    assert 'DATABASE_PATH' not in os.environ


def pytest_runtest_logreport(report):
    if report.skipped:
        pytest.exit('Пропуск тестов запрещён; требуется исправить причину.', returncode=1)


def pytest_collection_finish(session):
    if not session.items:
        pytest.exit('Не собраны тесты.', returncode=1)
