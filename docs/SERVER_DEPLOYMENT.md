# Native deployment on the two Ubuntu VMs

The application stays on server1 (`192.168.204.20`) in the existing `labapp.service`.
PostgreSQL 18 stays on server2 (`192.168.204.21`), with database `library` and runtime
role `labapp`. Run the database installer first. Both installers require one normal
interactive `sudo` invocation. Neither changes sudo policy or enables root SSH.

Use a reviewed release directory containing `requirements-lock.txt`, the application,
PostgreSQL migrations, `deploy/`, and a SHA256SUMS manifest. Exclude source `.env`,
virtual environments, caches, local databases and reports containing secrets.
Generate SHA256SUMS from the release root after the files are finalized:

```sh
find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
```

The installer accepts only a resolved directory under the matching VM's
`/home/server1/lab3-staging/release-*` or `/home/server2/lab3-staging/release-*` path.
It refuses symlinks in the staged tree, checks the manifest, copies to a root-owned
release and checks it again. Record and compare the release archive SHA256 through
the trusted deployment session as well; an adjacent manifest alone does not establish
who supplied the release.

On server2, substitute the actual staged release name:

```sh
sudo bash /home/server2/lab3-staging/release-ID/deploy/install-db.sh /home/server2/lab3-staging/release-ID
```

This saves a custom-format pre-update database dump, a protected globals dump
(which contains role password hashes), and PostgreSQL configuration before running
migrations. A new maintenance virtual environment uses the locked dependencies.
If the OS cannot create a working venv, the installer installs `python3-venv` using
APT, without upgrading other installed packages. Migrations run as OS/database
`postgres` through local peer authentication. Existing public tables, records and
schema objects remain in place. Migration metadata receives SELECT grants for the
app's independent dump; the app role receives no schema creation privileges.
The installer also checks SELECT privileges on the ID sequences of the eight
application tables that have numeric IDs (`sessions` uses a token key). INSERT
may work with sequence USAGE alone, while a complete pg_dump must read sequence
state. `deploy/backup-grants.sql` adds only missing SELECT grants to these known
sequences; a repeated run adds zero grants and does not grant schema CREATE.

After migrations, `deploy/lab3-demo.sql` adds an explicitly labelled DevOps training
author and branch, the book `ЛР3: автоматические проверки и резервное копирование`
with identifier `LAB3-DEVOPS-2026`, and two copies `LAB3-DEMO-001` and
`LAB3-DEMO-002`. The transaction takes the application's existing advisory lock
20261003, uses unique-key `ON CONFLICT DO NOTHING`, and records one guarded
`seed_demo` audit event. Re-running it preserves existing records and accounts
without duplicating the new catalog entries.

On server1:

```sh
sudo bash /home/server1/lab3-staging/release-ID/deploy/install-app.sh /home/server1/lab3-staging/release-ID
```

This saves the old application, effective unit definition and root-only environment
file under `/var/backups/library`. It builds a root-owned release and its virtual
environment at its permanent `/opt/labapp-releases/release-*` path. It checks the
candidate's database health as `labapp`, with systemd reading the existing
`/etc/labapp/labapp.env`. It takes an independent remote PostgreSQL backup before
the short service stop. `/opt/labapp` then becomes a symlink to the candidate;
the original directory or symlink is retained as `/opt/labapp-rollback-*`.
The existing service and all existing secrets are preserved. A failed HTTP health
check restores the previous application path and restarts the old service.

The app installer installs PostgreSQL client 18 only if `pg_dump` is missing and
installs `python3-venv` only if venv creation fails. No Docker or system upgrade is
performed. A package or candidate validation failure happens before the live service
is stopped. Failed candidates and pre-update backups are retained for inspection.

## Daily backups

Both VMs use the same standard-library runner at
`/usr/local/lib/library-backup/postgres_backup.py`. Backup files are root-owned,
mode 600, below root-owned mode 700 `/var/backups/library`. The DB VM service itself
runs as root so it can open these files; its PostgreSQL programs run as `postgres`
through `runuser`, using the local socket. The app VM service inherits the existing
database credentials from the root-only systemd EnvironmentFile. Passwords are
passed through `PGPASSWORD`, never command arguments or copied credential files.

| VM | Unit | Explicit schedule | Destination | Filename prefix |
| --- | --- | --- | --- | --- |
| server2 | `library-db-backup.timer` | 03:00 Europe/Moscow | `/var/backups/library/database` | `library-db` |
| server1 | `library-app-backup.timer` | 03:15 Europe/Moscow | `/var/backups/library/application` | `library-app` |

The schedule's explicit timezone works while the VMs stay on UTC. Both timers are
persistent, so a missed run executes after startup. Each successful run creates a
unique UTC timestamped custom archive. The runner checks `pg_restore --list`, syncs
the file and atomically renames `.dump.partial` to `.dump` before retention runs.
An OS lock prevents overlapping runs with the same prefix. Exactly the newest seven
successful files matching that runner's prefix/timestamp pattern are retained;
unrelated files, other prefixes and old partial files are not deleted. A failed
dump or validation removes its own partial file and leaves old backups intact.
Known pg_dump failures are reported using fixed diagnostic labels, including a
missing sequence SELECT privilege. Raw stderr, SQL details and passwords are not
written to the journal. pg_dump uses the C locale for consistent classification.
The manual `library-preupdate` and `library-verified` prefixes have independent
seven-copy retention. Configuration, globals and old release archives remain until
an operator reviews them; they are not included in daily dump retention.

Check each VM after installation:

```sh
sudo systemctl status library-db-backup.timer library-db-backup.service --no-pager
sudo journalctl -u library-db-backup.service -n 30 --no-pager
sudo systemctl list-timers --all library-db-backup.timer
```

Use `library-app-backup` instead on server1. A timer being active does not mean
its most recent backup succeeded: check service Result and the protected archive.
Run an immediate backup with `sudo systemctl start library-db-backup.service`
or the corresponding app service. Neither service changes application records.

## Restore verification without touching the working database

The DB installer runs this verification after migrations. It can also be repeated
manually on server2:

```sh
sudo env PATH=/usr/lib/postgresql/18/bin:/usr/sbin:/usr/bin:/bin \
  python3 /usr/local/lib/library-backup/postgres_backup.py \
  --output-directory /var/backups/library/database --database library \
  --prefix library-verified --as-postgres --validate-restore
```

Verification exports a read-only repeatable-read snapshot, records the counts of
all nine application tables and hashes of the first book, user and branch records,
and passes that same snapshot to `pg_dump`. It creates a fresh template0 database
named `library_restore_check_<UTC timestamp>_<random suffix>`, restores with
`--exit-on-error --single-transaction --no-owner --no-privileges`, and compares
restored counts and hashes to the exact source snapshot. No record contents or
password hashes are logged. Only the generated database is dropped in cleanup,
after its fixed prefix and format are checked. The working `library` database is
never a restore target. If the process is forcibly killed, inspect any leftover
`library_restore_check_*` database before manually deleting that exact generated DB.

This tests archive readability, schema/data recovery and control records. It does
not perform disaster recovery on the running service or replay the protected
globals dump. Keep the globals/configuration backup protected and restore it only
as a separate reviewed recovery action on the intended recovery server.

## Recovery of an application cutover

Automatic rollback applies to a failed initial cutover and health check. Old code
paths and root-only backups remain for a later manual rollback. Stop the service,
verify the chosen `/opt/labapp-rollback-*` path, and restore that exact directory or
symlink as `/opt/labapp`. The initial migrations are additive, so the old app can
continue using its existing schema. Do not restore a pre-update database over
`library` merely to roll back application code: that would discard later writes.
