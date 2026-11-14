#!/bin/sh
set -eu

export COMPOSE_PROJECT_NAME=library-ci
export COMPOSE_PROGRESS=plain
export HTTP_PORT=8080 DB_PORT=5432

db() { docker compose --env-file /dev/null -f compose.db.yml "$@"; }
app() { docker compose --env-file /dev/null "$@"; }
python() {
    docker run --rm -i -v /workspace:/workspace:ro -v /ci-cache/pip:/root/.cache/pip \
        -v /ci-reports:/ci-reports -w /workspace python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90 "$@"
}
node() { docker run --rm -v /workspace:/workspace:ro -w /workspace node:22.21.1-alpine node "$@"; }
report() {
    log=$1
    shift
    if "$@" > "$log" 2>&1; then
        cat "$log"
    else
        cat "$log"
        return 1
    fi
}
db_env() {
    export DB_BIND_IP="$(docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}')"
    export POSTGRES_PASSWORD="$(cat /tmp/library-ci/db-password)"
    export DATABASE_URL="postgresql://library:$POSTGRES_PASSWORD@$DB_BIND_IP:5432/library"
    export SECRET_KEY="$(cat /tmp/library-ci/app-key)"
    export DEMO_LIBRARIAN_PASSWORD="$(cat /tmp/library-ci/librarian-password)"
    export DEMO_READER_PASSWORD="$(cat /tmp/library-ci/reader-password)"
}
ready() { wget -T 8 -q -O - http://127.0.0.1:8080/health; }

case "$1" in
    style)
        report /ci-reports/style.txt python sh -ec '
            pip install -q -r requirements-ci.txt
            ruff check --no-cache app.py pg_adapter.py setup_local.py scripts tests
            PYTHONPYCACHEPREFIX=/tmp/pycache python -m compileall -q app.py pg_adapter.py scripts tests
        '
        node --check static/app.js
        python bash -ec 'for script in scripts/*.sh; do bash -n "$script"; done'
        ;;
    tests)
        report /ci-reports/python-tests.txt python sh -ec '
            pip install -q -r requirements-docker.txt
            PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
        '
        report /ci-reports/javascript-tests.tap node --test tests/test_ui.cjs
        ;;
    build)
        DATABASE_URL=placeholder SECRET_KEY=placeholder app build app1
        docker image inspect library-app:0.1.0 --format '{{.Id}}' > /ci-reports/image-id.txt
        ;;
    migrations)
        (umask 077
        mkdir -p /tmp/library-ci
        for name in db-password app-key librarian-password reader-password; do
            od -An -N32 -tx1 /dev/urandom | tr -d ' \n' > "/tmp/library-ci/$name"
        done)
        db_env
        db up -d --wait --wait-timeout 90
        report /ci-reports/migrations.txt app run --rm --no-deps app1 python app.py migrate
        app run --rm --no-deps app1 python app.py init-demo
        db exec -T db psql -U library -d library -v ON_ERROR_STOP=1 -Atc \
            'SELECT count(*) FROM books' | grep -qx 4
        ;;
    backup)
        db_env
        db exec -T db psql -U library -d library -v ON_ERROR_STOP=1 \
            -c "INSERT INTO authors(name) VALUES ('CI persistence marker')"
        db exec -T db pg_dump -U library -d library -Fc > /tmp/library-ci/library.dump
        db up -d --force-recreate --wait --wait-timeout 90
        query="SELECT count(*) FROM authors WHERE name='CI persistence marker'"
        test "$(db exec -T db psql -U library -d library -Atc "$query")" = 1
        export DB_BIND_IP=127.0.0.1 DB_PORT=15432
        docker compose --env-file /dev/null -p library-ci-restore -f compose.db.yml up -d --wait --wait-timeout 90
        docker compose --env-file /dev/null -p library-ci-restore -f compose.db.yml exec -T db \
            pg_restore -U library -d library --exit-on-error --single-transaction < /tmp/library-ci/library.dump
        test "$(docker compose --env-file /dev/null -p library-ci-restore -f compose.db.yml exec -T db \
            psql -U library -d library -Atc "$query")" = 1
        echo 'Marker survived recreation and was recovered in an independent volume.' > /ci-reports/backup.txt
        ;;
    security)
        rc=0
        docker run --rm -v /workspace:/workspace:ro -v /ci-reports:/ci-reports \
            -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0=/workspace \
            zricethezav/gitleaks:v8.30.1 git /workspace --log-opts=HEAD --redact=100 \
            --report-format json --report-path /ci-reports/secrets.json || rc=1
        report /ci-reports/dependencies.txt python sh -ec '
            pip install -q -r requirements-ci.txt
            pip-audit --strict -r requirements-docker.txt -f json -o /ci-reports/dependencies.json
        ' || rc=1
        if ! docker image inspect library-app:0.1.0 >/dev/null 2>&1; then exit "$rc"; fi
        docker save library-app:0.1.0 -o /tmp/library-ci-image.tar
        report /ci-reports/image-scan.txt docker run --rm \
            -v /tmp/library-ci-image.tar:/image.tar:ro -v /ci-reports:/ci-reports \
            -v /ci-cache/trivy:/root/.cache/trivy aquasec/trivy:0.76.2 image \
            --input /image.tar --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed \
            --exit-code 1 --format json --output /ci-reports/image-scan.json || rc=1
        if [ -f /ci-reports/image-scan.json ]; then
            python python -c 'import json; data=json.load(open("/ci-reports/image-scan.json")); print(*((v["VulnerabilityID"],v["PkgName"],v.get("InstalledVersion"),v.get("FixedVersion")) for r in data.get("Results",[]) for v in r.get("Vulnerabilities",[])),sep="\n")'
        fi
        exit "$rc"
        ;;
    containers)
        db_env
        app config --format json | python python scripts/check-compose.py app --stdin
        db config --format json | python python scripts/check-compose.py db --stdin
        test "$(docker image inspect library-app:0.1.0 --format '{{.Config.User}}')" = '10001:10001'
        app up -d --no-build --wait --wait-timeout 90
        ready
        app exec -T nginx wget -q -O /dev/null http://127.0.0.1:8080/
        wget -q -O /dev/null --header='Content-Type: application/json' \
            --post-data="{\"username\":\"librarian\",\"password\":\"$DEMO_LIBRARIAN_PASSWORD\"}" \
            http://127.0.0.1:8080/api/auth/login
        instances=$(for i in 1 2 3 4 5 6; do
            wget -S -O /dev/null http://127.0.0.1:8080/health 2>&1 | awk 'tolower($1)=="x-instance-id:" {print $2}'
        done)
        test "$(printf '%s\n' "$instances" | sort -u | wc -l)" -eq 2
        survivor=$(app exec -T app2 hostname)
        app stop app1
        # Docker DNS removes the stopped replica asynchronously.
        recovered=0
        for attempt in 1 2 3 4 5 6; do
            if headers=$(wget -T 4 -S -O /dev/null http://127.0.0.1:8080/health 2>&1) &&
                printf '%s\n' "$headers" | awk -v id="$survivor" '
                    tolower($1) == "x-instance-id:" && $2 == id { found = 1 }
                    END { exit !found }
                '; then
                recovered=1
                break
            fi
            printf 'Failover probe %s has not reached app2\n' "$attempt"
            sleep 1
        done
        if [ "$recovered" -ne 1 ]; then
            app logs --tail 40 nginx app2
            exit 1
        fi
        printf 'Failover reached app2 (%s) on attempt %s\n' "$survivor" "$attempt" > /ci-reports/failover.txt
        test "$(docker inspect "$(app ps -aq app1)" --format '{{.State.ExitCode}}')" = 0
        app start app1
        printf '%s\n' "$instances" > /ci-reports/instances.txt
        ;;
    registry)
        tag="sha-$CI_COMMIT_SHA"
        docker run -d --name library-registry -p 127.0.0.1:5000:5000 registry:3.0.0
        for i in $(seq 1 30); do
            if wget -q -O /dev/null http://127.0.0.1:5000/v2/; then break; fi
            sleep 1
        done
        local_image="127.0.0.1:5000/library-app:$tag"
        docker tag library-app:0.1.0 "$local_image"
        docker push "$local_image" > /ci-reports/registry.txt
        wget -q -O - http://127.0.0.1:5000/v2/library-app/tags/list | grep -F "$tag" >> /ci-reports/registry.txt
        docker save library-app:0.1.0 -o /tmp/library-ci-image.tar
        gzip -c /tmp/library-ci-image.tar > /ci-reports/library-app.tar.gz
        ;;
    *) echo "Unknown CI stage: $1" >&2; exit 2 ;;
esac
