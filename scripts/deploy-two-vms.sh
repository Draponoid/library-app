#!/usr/bin/env bash
# First deployment from VM1 to VM2. Existing deployments are never overwritten.
set -Eeuo pipefail
if [[ $# != 3 ]]; then echo "Usage: bash scripts/deploy-two-vms.sh VM1_IP VM2_IP SSH_USER@VM2" >&2; exit 2; fi
APP_IP=$1 DB_IP=$2 DB_SSH=$3
for ip in "$APP_IP" "$DB_IP"; do
  [[ $ip =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || { echo "Invalid IPv4: $ip" >&2; exit 2; }
  IFS=. read -r a b c d <<< "$ip"
  for n in "$a" "$b" "$c" "$d"; do ((10#$n <= 255)) || { echo "Invalid IPv4: $ip" >&2; exit 2; }; done
done
[[ $DB_SSH =~ ^[a-zA-Z_][a-zA-Z0-9_.-]*@[a-zA-Z0-9_.-]+$ ]] || { echo 'Use SSH_USER@VM2 address' >&2; exit 2; }
cd "$(dirname "$0")/.."
[[ -d .git ]] || { echo 'Run from a Git checkout' >&2; exit 1; }
[[ -z $(git status --porcelain) ]] || { echo 'Commit or stash changes before deployment' >&2; exit 1; }
[[ ! -e .env ]] || { echo '.env already exists; refusing to overwrite an existing deployment' >&2; exit 1; }
ref=$(git symbolic-ref --short HEAD)
[[ $ref =~ ^[a-zA-Z0-9._/-]+$ && $ref != -* ]] || { echo 'Invalid branch name' >&2; exit 1; }
revision=$(git rev-parse HEAD)
[[ $revision =~ ^[0-9a-f]{40}$ ]] || exit 1
SSH=(ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 "$DB_SSH")
sudo -n true
"${SSH[@]}" 'sudo -n true && test ! -e "$HOME/library-lab4-db"'
bash scripts/install-ubuntu.sh
"${SSH[@]}" 'bash -s' < scripts/install-ubuntu.sh
# The same published revision is used on both VMs.
"${SSH[@]}" "git clone --branch '$ref' https://github.com/Draponoid/library-app.git \"\$HOME/library-lab4-db\" && cd \"\$HOME/library-lab4-db\" && git checkout --detach '$revision'"
umask 077
DB_PASS=$(openssl rand -hex 24)
printf 'DATABASE_URL=postgresql://library:%s@%s:5432/library\nSECRET_KEY=%s\nDEMO_LIBRARIAN_PASSWORD=%s\nDEMO_READER_PASSWORD=%s\nHTTP_PORT=8080\n' "$DB_PASS" "$DB_IP" "$(openssl rand -hex 32)" "$(openssl rand -hex 12)" "$(openssl rand -hex 12)" > .env
printf 'DB_BIND_IP=%s\nPOSTGRES_PASSWORD=%s\n' "$DB_IP" "$DB_PASS" | "${SSH[@]}" 'umask 077; cat > "$HOME/library-lab4-db/.env"'
unset DB_PASS
# Validate the database environment before changing the container firewall or starting it.
"${SSH[@]}" 'cd "$HOME/library-lab4-db" && sudo -n make container-check MODE=db'
"${SSH[@]}" "cd \"\$HOME/library-lab4-db\" && sudo -n bash scripts/install-db-firewall.sh '$APP_IP' '$DB_IP'"
"${SSH[@]}" 'cd "$HOME/library-lab4-db" && sudo -n make db-up'
for i in {1..60}; do
  if "${SSH[@]}" 'cd "$HOME/library-lab4-db" && sudo -n docker compose -f compose.db.yml exec -T db pg_isready -U library -d library' >/dev/null 2>&1; then break; fi
  sleep 2
done
"${SSH[@]}" 'cd "$HOME/library-lab4-db" && sudo -n docker compose -f compose.db.yml exec -T db pg_isready -U library -d library'
sudo -n make migrate
sudo -n make seed
sudo -n make up
if command -v ufw >/dev/null && sudo -n ufw status | grep -q '^Status: active'; then
  sudo -n ufw allow 8080/tcp
fi
curl --retry 10 --retry-delay 2 --retry-connrefused -fsS http://127.0.0.1:8080/health
printf '\nReady: http://%s:8080\nCredentials: %s/.env (librarian and reader).\n' "$APP_IP" "$PWD"
