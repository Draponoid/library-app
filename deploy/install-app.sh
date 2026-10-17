#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
export PATH=/usr/lib/postgresql/18/bin:/usr/sbin:/usr/bin:/sbin:/bin
[[ $EUID == 0 ]] || { echo 'Run this installer with sudo.' >&2; exit 1; }
[[ $# == 1 ]] || { echo 'Usage: install-app.sh /home/server1/lab3-staging/release-ID' >&2; exit 1; }
release=$(realpath -e -- "$1")
[[ $release == /home/server1/lab3-staging/release-* && -d $release ]] || { echo 'Unexpected staging path.' >&2; exit 1; }
[[ -f $release/SHA256SUMS && -z $(find "$release" -type l -print -quit) ]] || { echo 'Manifest missing or staging contains symlinks.' >&2; exit 1; }
(cd "$release" && sha256sum --check --strict SHA256SUMS >/dev/null)
[[ -d /opt/labapp && -f /etc/labapp/labapp.env ]] || { echo 'Existing application or configuration missing.' >&2; exit 1; }
current=$(realpath -e /opt/labapp)
[[ $current == /opt/labapp || $current == /opt/labapp-releases/release-* ]] || { echo 'Unexpected current release path.' >&2; exit 1; }
stamp=$(date -u +%Y%m%dT%H%M%S)
install -d -m 700 /var/backups/library /var/backups/library/application
install -d -m 755 /opt/labapp-releases /usr/local/lib/library-backup
candidate=$(mktemp -d "/opt/labapp-releases/release-${stamp}-XXXXXX")
cp -a "$release/." "$candidate/"
chown -R root:labapp "$candidate"
find "$candidate" -type d -exec chmod 750 {} +
find "$candidate" -type f -exec chmod 640 {} +
(cd "$candidate" && sha256sum --check --strict SHA256SUMS >/dev/null)
tar -czf "/var/backups/library/application-before-${stamp}.tar.gz" -C "$current" .
install -m 600 /etc/labapp/labapp.env "/var/backups/library/labapp-env-${stamp}"
systemctl cat labapp.service >"/var/backups/library/labapp-unit-${stamp}.txt"
if ! command -v pg_dump >/dev/null; then
    apt-get update
    apt-get install --no-upgrade -y postgresql-client-18
fi
if ! python3 -m venv "$candidate/venv" >/dev/null 2>&1; then
    apt-get update
    apt-get install --no-upgrade -y python3-venv
    python3 -m venv "$candidate/venv"
fi
"$candidate/venv/bin/python" -m pip install --disable-pip-version-check -r "$candidate/requirements-lock.txt"
chown -R root:labapp "$candidate/venv"
chmod -R g+rX "$candidate/venv"
runuser -u labapp -- "$candidate/venv/bin/gunicorn" --version

# systemd reads the existing root-only secret file; it is never parsed or printed here.
systemd-run --quiet --wait --pipe --unit="labapp-candidate-check-${stamp}" \
    --property=User=labapp --property=Group=labapp --property="WorkingDirectory=$candidate" \
    --property=EnvironmentFile=/etc/labapp/labapp.env \
    "$candidate/venv/bin/python" -c \
    'from app import create_app; a=create_app(); r=a.test_client().get("/health"); assert r.status_code==200, "Candidate health check failed"; print("Candidate database health passed")'
install -m 644 "$candidate/deploy/postgres_backup.py" /usr/local/lib/library-backup/postgres_backup.py
systemd-run --quiet --wait --pipe --unit="labapp-preupdate-backup-${stamp}" \
    --property=EnvironmentFile=/etc/labapp/labapp.env \
    /usr/bin/python3 /usr/local/lib/library-backup/postgres_backup.py \
    --output-directory /var/backups/library/application --prefix library-preupdate
install -m 644 "$candidate/deploy/library-app-backup.service" /etc/systemd/system/library-app-backup.service
install -m 644 "$candidate/deploy/library-app-backup.timer" /etc/systemd/system/library-app-backup.timer
systemd-analyze verify /etc/systemd/system/library-app-backup.service /etc/systemd/system/library-app-backup.timer
systemctl daemon-reload

rollback="/opt/labapp-rollback-${stamp}"
[[ ! -e $rollback && ! -L $rollback ]] || { echo 'Rollback path already exists.' >&2; exit 1; }
switched=0
recover() {
    code=$?
    if (( switched )); then
        systemctl stop labapp.service || true
        if [[ -L /opt/labapp && $(readlink /opt/labapp) == "$candidate" ]]; then
            unlink /opt/labapp
            mv -- "$rollback" /opt/labapp
            systemctl start labapp.service || true
            echo 'Health check failed; previous application path restored.' >&2
        elif [[ ! -e /opt/labapp && ! -L /opt/labapp ]]; then
            mv -- "$rollback" /opt/labapp
            systemctl start labapp.service || true
            echo 'Cutover failed; previous application path restored.' >&2
        else
            echo "Unexpected application path; manual recovery is available at $rollback" >&2
        fi
    fi
    exit "$code"
}
trap recover ERR
systemctl stop labapp.service
mv -- /opt/labapp "$rollback"
switched=1
ln -s -- "$candidate" /opt/labapp
systemctl start labapp.service
healthy=0
for attempt in {1..30}; do
    if /usr/bin/python3 -c 'import urllib.request; urllib.request.urlopen("http://192.168.204.20:5000/health", timeout=3).read()' >/dev/null 2>&1; then
        healthy=1
        break
    fi
    sleep 1
done
[[ $healthy == 1 ]]
systemctl is-active --quiet labapp.service
switched=0
trap - ERR
systemctl enable --now library-app-backup.timer
systemctl start library-app-backup.service
echo "Application deployment completed: $candidate"
echo "Previous application path retained at $rollback"
