#!/usr/bin/env bash
# Validate staging before replacing running containers. No image is built here.
set -Eeuo pipefail
: "${STAGING_DIR:?Set STAGING_DIR}" "${RELEASE_IMAGE:?Set RELEASE_IMAGE}" "${RELEASE_TAG:?Set RELEASE_TAG}"
compose=(docker compose --project-name library-stage --env-file "$STAGING_DIR/.env" -f compose.release.yml)
python3 scripts/smoke-release.py "$STAGING_DIR/.env" "$RELEASE_TAG" --preflight
"${compose[@]}" config --quiet
"${compose[@]}" config --format json | python3 scripts/check-release.py
"${compose[@]}" pull app1 app2 nginx
docker image inspect "$RELEASE_IMAGE" --format '{{.Config.User}}' | grep -Fx '10001:10001' >/dev/null
actual=$(docker image inspect "$RELEASE_IMAGE" --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^APP_VERSION=//p')
[[ $actual == "$RELEASE_TAG" ]] || { echo 'Image version does not match requested tag' >&2; exit 1; }
echo 'container-check: OK'
