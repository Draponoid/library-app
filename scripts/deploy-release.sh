#!/usr/bin/env bash
# Deploy an already published SHA-tagged image to the isolated staging project.
set -Eeuo pipefail
[[ $# == 1 && $1 =~ ^sha-[0-9a-f]{40}$ ]] || { echo 'Expected image tag sha-<40 lowercase hex characters>' >&2; exit 2; }
tag=$1
: "${STAGING_DIR:?Set STAGING_DIR to an absolute directory containing .env}"
[[ $STAGING_DIR == /* && -d $STAGING_DIR && -f $STAGING_DIR/.env ]] || { echo 'Missing staging directory or .env' >&2; exit 2; }
cd "$(dirname "$0")/.."
repository=${RELEASE_REPOSITORY:-ghcr.io/draponoid/library-app}
[[ $repository =~ ^[a-z0-9][a-z0-9./:-]*[a-z0-9]$ && $repository != *..* ]] || { echo 'Invalid image repository' >&2; exit 2; }
export RELEASE_IMAGE="$repository:$tag"
compose=(docker compose --project-name library-stage --env-file "$STAGING_DIR/.env" -f compose.release.yml)
exec 9>"$STAGING_DIR/deploy.lock"
flock -n 9 || { echo 'Another deployment is running' >&2; exit 1; }
export RELEASE_TAG="$tag"
make container-check MODE=release
"${compose[@]}" up -d --no-build
# Check both containers, not just one request through the load balancer.
for service in app1 app2 nginx; do
  container=$("${compose[@]}" ps -q "$service")
  [[ -n $container ]] || { echo "$service is missing" >&2; exit 1; }
  ready=false
  for _ in {1..60}; do
    status=$(docker inspect --format '{{.State.Health.Status}}' "$container")
    if [[ $status == healthy ]]; then ready=true; break; fi
    sleep 2
  done
  [[ $ready == true ]] || { echo "$service did not become healthy" >&2; exit 1; }
done
for service in app1 app2; do
  version=$("${compose[@]}" exec -T "$service" python -c 'import json,urllib.request; print(json.load(urllib.request.urlopen("http://127.0.0.1:5000/version",timeout=3))["version"])')
  [[ $version == "$tag" ]] || { echo "$service reports a different version" >&2; exit 1; }
done
python3 scripts/smoke-release.py "$STAGING_DIR/.env" "$tag"
printf '%s\n' "$tag" > "$STAGING_DIR/active-tag.tmp"
mv -f "$STAGING_DIR/active-tag.tmp" "$STAGING_DIR/active-tag"
echo "Verified release: $tag"
