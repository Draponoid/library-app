#!/bin/sh
set -eu

name=${CI_DIND_NAME:-library-ci-$$}
cache=${CI_CACHE_DIR:-$(pwd -P)/.ci-cache}
reports=${CI_REPORT_DIR:-$(pwd -P)/.ci-reports}
mkdir -p "$cache" "$reports"

start() {
    docker run -d --privileged --name "$name" \
        --env DOCKER_TLS_CERTDIR= --workdir /workspace \
        --mount "type=bind,src=$(pwd -P),dst=/workspace,readonly" \
        --mount "type=bind,src=$cache,dst=/ci-cache" \
        --mount "type=bind,src=$reports,dst=/ci-reports" \
        docker:28.5.2-dind dockerd --host=unix:///var/run/docker.sock >/dev/null
    for i in $(seq 1 60); do
        if docker exec "$name" docker info >/dev/null 2>&1; then return; fi
        sleep 1
    done
    docker logs "$name" >&2
    return 1
}

stop() {
    docker rm -fv "$name" >/dev/null 2>&1 || true
}

run() {
    docker exec --env CI_COMMIT_SHA="${CI_COMMIT_SHA:-$(git rev-parse HEAD)}" \
        "$name" sh scripts/ci.sh "$1"
}

case "${1:-all}" in
    start) start ;;
    stop) stop ;;
    all)
        trap stop EXIT
        start
        for stage in style tests build migrations backup security containers registry; do
            run "$stage"
        done
        ;;
    *) run "$1" ;;
esac
