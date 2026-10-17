"""Explicit configuration, independent from the developer's .env."""

TEST_CONFIG = {
    'TESTING': True,
    'SECRET_KEY': 'test-only-secret-' * 4,
    'SESSION_HOURS': 8,
    'COOKIE_SECURE': False,
    'LOAN_DAYS': 14,
    'MAX_ACTIVE_LOANS': 5,
}
