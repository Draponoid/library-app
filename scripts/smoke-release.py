"""Check staging configuration, then health, version, login and catalogue."""
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


def settings(path):
    result = {}
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        name, separator, value = line.partition('=')
        if not separator or not name.replace('_', '').isalnum():
            raise ValueError('Invalid .env entry')
        result[name] = value.strip().strip('"').strip("'")
    for key in ('DATABASE_URL', 'SECRET_KEY', 'CD_SMOKE_USERNAME', 'CD_SMOKE_PASSWORD'):
        if not result.get(key):
            raise ValueError(f'Missing {key} in staging .env')
    port = int(result.get('HTTP_PORT', '8081'))
    if not 1 <= port <= 65535:
        raise ValueError('Invalid HTTP_PORT')
    return result, port


def run():
    env, port = settings(sys.argv[1])
    if len(sys.argv) > 3 and sys.argv[3] == '--preflight':
        print('Staging configuration: OK')
        return
    expected = sys.argv[2]
    base = f'http://127.0.0.1:{port}'
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(path, payload=None, headers=None):
        data = json.dumps(payload).encode() if payload is not None else None
        headers = dict(headers or {})
        if data is not None:
            headers['Content-Type'] = 'application/json'
        with opener.open(urllib.request.Request(base + path, data=data, headers=headers), timeout=10) as response:
            return json.load(response)

    health = request('/health')
    if health.get('status') != 'ok' or health.get('database') != 'ok':
        raise ValueError('Health check failed')
    if request('/version').get('version') != expected:
        raise ValueError('Running version differs from requested tag')
    login = request('/api/auth/login', {'username': env['CD_SMOKE_USERNAME'], 'password': env['CD_SMOKE_PASSWORD']})
    if not isinstance(login.get('csrf_token'), str):
        raise ValueError('Login did not return a CSRF token')
    if not isinstance(request('/api/books').get('items'), list):
        raise ValueError('Catalogue response is invalid')
    request('/api/auth/logout', {}, {'X-CSRF-Token': login['csrf_token']})
    print('Health, version, login and catalogue: OK')


if __name__ == '__main__':
    try:
        run()
    except (ValueError, OSError, urllib.error.URLError, KeyError, IndexError) as error:
        print(f'Release check failed: {error}', file=sys.stderr)
        raise SystemExit(1)
