"""Validate the resolved release configuration without printing secrets."""
import json
import sys


def require(condition, message):
    if not condition:
        raise ValueError(message)


try:
    config = json.load(sys.stdin)
    services = config['services']
    require(set(services) == {'app1', 'app2', 'nginx'}, 'Unexpected services')
    for name, service in services.items():
        image = service.get('image', '')
        require(':' in image.rsplit('/', 1)[-1] and not image.split('@')[0].endswith(':latest'), f'{name}: invalid image')
        require(not service.get('build'), f'{name}: building on server is forbidden')
        health = service.get('healthcheck') or {}
        require(bool(health) and not health.get('disable') and health.get('test') != ['NONE'], f'{name}: healthcheck required')
        require(service.get('mem_limit') and service.get('cpus'), f'{name}: resource limits required')
        require(not service.get('privileged'), f'{name}: privileged mode forbidden')
        if name in ('app1', 'app2'):
            require(not service.get('ports'), f'{name}: published port forbidden')
            require(service.get('user') in (None, '10001:10001'), f'{name}: invalid user')
    require(services['nginx'].get('user') not in (None, '', '0', 'root', '0:0'), 'nginx: root forbidden')
    require(config['networks']['backend'].get('internal'), 'backend must be internal')
    require(len(services['nginx'].get('ports', [])) == 1, 'nginx: one published port required')
except (ValueError, KeyError, TypeError) as error:
    print(f'Release configuration rejected: {error}', file=sys.stderr)
    raise SystemExit(1)
print('Release configuration: OK')
