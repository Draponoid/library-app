#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
export PATH=/usr/lib/postgresql/18/bin:/usr/sbin:/usr/bin:/sbin:/bin
[[ $EUID == 0 ]] || { echo 'Run this installer with sudo.' >&2; exit 1; }
[[ $# == 1 ]] || { echo 'Usage: install-db.sh /home/server2/lab3-staging/release-ID' >&2; exit 1; }
release=$(realpath -e -- "$1")
[[ $release == /home/server2/lab3-staging/release-* && -d $release ]] || { echo 'Unexpected staging path.' >&2; exit 1; }
[[ -f $release/SHA256SUMS && -z $(find "$release" -type l -print -quit) ]] || { echo 'Manifest missing or staging contains symlinks.' >&2; exit 1; }
(cd "$release" && sha256sum --check --strict SHA256SUMS >/dev/null)
stamp=$(date -u +%Y%m%dT%H%M%S)
install -d -m 700 /var/backups/library /var/backups/library/database
install -d -m 755 /opt/library-maintenance /usr/local/lib/library-backup
candidate=$(mktemp -d "/opt/library-maintenance/release-${stamp}-XXXXXX")
chmod 755 "$candidate"
cp -a "$release/." "$candidate/"
chown -R root:root "$candidate"
find "$candidate" -type d -exec chmod 755 {} +
find "$candidate" -type f -exec chmod 644 {} +
(cd "$candidate" && sha256sum --check --strict SHA256SUMS >/dev/null)

# Take independent recoverable pre-update artifacts before migrations or grants.
python3 "$candidate/deploy/postgres_backup.py" --output-directory /var/backups/library/database \
    --database library --prefix library-preupdate --as-postgres
globals="/var/backups/library/globals-${stamp}.sql"
runuser -u postgres -- pg_dumpall --globals-only >"$globals.partial"
mv -- "$globals.partial" "$globals"
tar -czf "/var/backups/library/postgresql-config-${stamp}.tar.gz" -C /etc postgresql postgresql-common

if ! python3 -m venv "$candidate/venv" >/dev/null 2>&1; then
    apt-get update
    apt-get install --no-upgrade -y python3-venv
    python3 -m venv "$candidate/venv"
fi
"$candidate/venv/bin/python" -m pip install --disable-pip-version-check -r "$candidate/requirements-lock.txt"
chmod -R a+rX "$candidate/venv"
cd "$candidate"
runuser -u postgres -- "$candidate/venv/bin/python" -c \
    'from database import migrate_postgres; migrate_postgres({"host":"/var/run/postgresql", "port":5432, "dbname":"library", "user":"postgres"})'
runuser -u postgres -- psql --no-psqlrc --set ON_ERROR_STOP=1 --dbname library \
    --file "$candidate/deploy/lab3-demo.sql"
# Runtime remains unable to create tables; only backup visibility is added for migration metadata.
runuser -u postgres -- psql --no-psqlrc --set ON_ERROR_STOP=1 --dbname library <<'SQL'
DO $grant$
DECLARE relation record;
BEGIN
  FOR relation IN SELECT tablename FROM pg_tables WHERE schemaname='public'
      AND (tablename LIKE '\_yoyo%' ESCAPE '\' OR tablename = 'yoyo_lock')
  LOOP
    EXECUTE format('GRANT SELECT ON TABLE public.%I TO labapp', relation.tablename);
  END LOOP;
END
$grant$;
SQL
runuser -u postgres -- psql --no-psqlrc --set ON_ERROR_STOP=1 --dbname library \
    --file "$candidate/deploy/backup-grants.sql"
install -m 644 "$candidate/deploy/postgres_backup.py" /usr/local/lib/library-backup/postgres_backup.py
install -m 644 "$candidate/deploy/library-db-backup.service" /etc/systemd/system/library-db-backup.service
install -m 644 "$candidate/deploy/library-db-backup.timer" /etc/systemd/system/library-db-backup.timer
systemd-analyze verify /etc/systemd/system/library-db-backup.service /etc/systemd/system/library-db-backup.timer
systemctl daemon-reload
systemctl enable --now library-db-backup.timer
systemctl start library-db-backup.service
# Validate the real backup by restoring to a generated isolated DB and removing only that DB.
python3 /usr/local/lib/library-backup/postgres_backup.py --output-directory /var/backups/library/database \
    --database library --prefix library-verified --as-postgres --validate-restore
echo "Database deployment completed; maintenance release: $candidate"
echo 'Protected pre-update dump, globals and configuration are in /var/backups/library.'
