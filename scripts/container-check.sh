#!/bin/sh
set -eu
# Validate the exact Compose configuration and the built image before changing it.
if [ "${MODE:-app}" = db ]; then
  docker compose -f compose.db.yml config --quiet
  python3 scripts/check-compose.py db
  docker compose -f compose.db.yml pull
  exit 0
fi
docker compose config --quiet
python3 scripts/check-compose.py app
docker compose build app1
id=$(docker image inspect library-app:0.1.0 --format '{{.Config.User}}')
[ "$id" = '10001:10001' ] || { echo 'Application image must be non-root' >&2; exit 1; }
docker compose run --rm --no-deps --entrypoint python app1 -c 'import os, psycopg; assert os.getuid() != 0; c=psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=5); c.execute("SELECT 1"); c.close()'
echo 'container-check: OK'
