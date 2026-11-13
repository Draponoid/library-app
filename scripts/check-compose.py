"""Fail closed when deployment configuration violates the lab policy."""
import json
import subprocess
import sys


def config(*args):
    return json.loads(subprocess.check_output(['docker', 'compose', *args, 'config', '--format', 'json']))


mode = sys.argv[1] if len(sys.argv) > 1 else 'app'
app = config() if mode == 'app' else None
db = config('-f', 'compose.db.yml') if mode == 'db' else None
services = app['services'] if app else db['services']
for name, spec in services.items():
    image = spec.get('image', '')
    assert ':' in image.rsplit('/', 1)[-1] and not image.split('@', 1)[0].endswith(':latest'), (name, 'image tag')
    assert spec.get('healthcheck') and not spec['healthcheck'].get('disable'), (name, 'healthcheck')
    assert spec.get('mem_limit') and spec.get('cpus'), (name, 'resource limits')
    assert not spec.get('privileged'), (name, 'privileged')
    if name in ('app1', 'app2'):
        assert not spec.get('ports'), (name, 'application port published')
        assert spec.get('user') in (None, '10001:10001'), (name, 'unexpected user override')
    else:
        assert spec.get('user') not in (None, '', '0', 'root', '0:0'), (name, 'root')
if app:
    assert app['networks']['backend'].get('internal'), 'backend must be internal'
else:
    assert len(db['services']['db'].get('ports', [])) == 1, 'DB needs one VM-to-VM port'
    assert 'db-data' in db.get('volumes', {}), 'DB volume missing'
assert open('.dockerignore', encoding='utf-8').read().startswith('**'), 'build context must be allowlisted'
print('Compose policy: OK')
