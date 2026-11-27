#!/usr/bin/env bash
# CI integration test with a disposable local registry and staging project.
set -Eeuo pipefail
: "${RUNNER_TEMP:?}" "${RELEASE_VERSION:?}"
export STAGING_DIR="$RUNNER_TEMP/library-stage"
export RELEASE_REPOSITORY=127.0.0.1:5050/library-app
mkdir -p "$STAGING_DIR"
cp .env "$STAGING_DIR/.env"
printf '%s\n' 'HTTP_PORT=18081' 'CD_SMOKE_USERNAME=librarian' 'CD_SMOKE_PASSWORD=integration-test-password-1' >> "$STAGING_DIR/.env"
docker run -d --name release-test-registry -p 127.0.0.1:5050:5000 registry:2.8.3@sha256:a3d8aaa63ed8681a604f1dea0aa03f100d5895b6a58ace528858a7b332415373
for i in {1..30}; do
  if curl -fsS http://127.0.0.1:5050/v2/ >/dev/null; then break; fi
  sleep 1
done
docker tag library-app:0.1.0 "$RELEASE_REPOSITORY:$RELEASE_VERSION"
docker push "$RELEASE_REPOSITORY:$RELEASE_VERSION"
bash scripts/deploy-release.sh "$RELEASE_VERSION"
test "$(cat "$STAGING_DIR/active-tag")" = "$RELEASE_VERSION"
if bash scripts/deploy-release.sh invalid; then echo 'Invalid tag accepted' >&2; exit 1; fi
missing="$RUNNER_TEMP/library-stage-missing"
mkdir -p "$missing"
sed '/^SECRET_KEY=/d' "$STAGING_DIR/.env" > "$missing/.env"
if STAGING_DIR="$missing" bash scripts/deploy-release.sh "$RELEASE_VERSION"; then echo 'Missing secret accepted' >&2; exit 1; fi
missing_tag=sha-2222222222222222222222222222222222222222
if bash scripts/deploy-release.sh "$missing_tag"; then echo 'Missing image accepted' >&2; exit 1; fi
if RELEASE_REPOSITORY=127.0.0.1:65534/library-app bash scripts/deploy-release.sh "$RELEASE_VERSION"; then echo 'Offline registry accepted' >&2; exit 1; fi
bad_tag=sha-1111111111111111111111111111111111111111
docker build --build-arg RELEASE_VERSION="$bad_tag" -t "$RELEASE_REPOSITORY:$bad_tag" .
docker push "$RELEASE_REPOSITORY:$bad_tag"
sed -i 's/^CD_SMOKE_PASSWORD=.*/CD_SMOKE_PASSWORD=wrong-password/' "$STAGING_DIR/.env"
if bash scripts/deploy-release.sh "$bad_tag"; then echo 'Broken user scenario accepted' >&2; exit 1; fi
test "$(cat "$STAGING_DIR/active-tag")" = "$RELEASE_VERSION"
sed -i 's/^CD_SMOKE_PASSWORD=.*/CD_SMOKE_PASSWORD=integration-test-password-1/' "$STAGING_DIR/.env"
bash scripts/deploy-release.sh "$RELEASE_VERSION"
test "$(cat "$STAGING_DIR/active-tag")" = "$RELEASE_VERSION"
# Simulate healthy process but failed health check by disconnecting its DB.
cp "$STAGING_DIR/.env" "$STAGING_DIR/.env.good"
sed -i 's|^DATABASE_URL=.*|DATABASE_URL=postgresql://library:wrong@127.0.0.1:6543/library|' "$STAGING_DIR/.env"
if bash scripts/deploy-release.sh "$bad_tag"; then echo 'Unhealthy release accepted' >&2; exit 1; fi
test "$(cat "$STAGING_DIR/active-tag")" = "$RELEASE_VERSION"
mv -f "$STAGING_DIR/.env.good" "$STAGING_DIR/.env"
bash scripts/deploy-release.sh "$RELEASE_VERSION"
test "$(cat "$STAGING_DIR/active-tag")" = "$RELEASE_VERSION"
