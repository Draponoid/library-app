#!/usr/bin/env bash
# Exercises both deployments, idempotence and drift on a disposable Linux CI runner.
set -Eeuo pipefail
: "${RUNNER_TEMP:?}"
base="$RUNNER_TEMP/library-lab7-test"
mkdir -p "$base"
ssh-keygen -q -t ed25519 -N '' -f "$base/test-key"
bridge=$(ip -4 -o addr show docker0 | awk '{print $4}' | cut -d/ -f1)
cat > "$base/ci-vars.yml" <<EOF
ci_docker_host: "$bridge"
lab_base_dir: "$base/managed"
lab_app_image: "library-lab7-ci:ci"
lab_deploy_public_key: "$(cat "$base/test-key.pub")"
lab_manage_packages: false
lab_manage_ssh: false
lab_manage_firewall: false
lab_allow_example_addresses: true
lab_environment: prod
lab_http_port: 18082
lab_db_port: 15542
EOF
printf '%s\n' 'ci-only-vault-passphrase' > "$base/vault-pass"
chmod 600 "$base/vault-pass"
cat > "$base/vault.yml" <<EOF
vault_db_password: "$(openssl rand -hex 24)"
vault_secret_key: "$(openssl rand -hex 32)"
vault_demo_librarian_password: "$(openssl rand -hex 12)"
vault_demo_reader_password: "$(openssl rand -hex 12)"
EOF
ansible-vault encrypt --vault-password-file "$base/vault-pass" "$base/vault.yml"
export ANSIBLE_CONFIG="$PWD/infra/ansible.cfg" ANSIBLE_NOCOLOR=1
play=(ansible-playbook -i infra/inventories/ci/hosts.yml infra/site.yml -e "@$base/ci-vars.yml" -e "@$base/vault.yml" --vault-password-file "$base/vault-pass")
docker build -t library-lab7-ci:ci .
"${play[@]}"
"${play[@]}" | tee "$base/second-run.log"
python3 infra/check_idempotence.py "$base/second-run.log"
nginx="$base/managed/prod/application/nginx.conf"
before=$(sudo sha256sum "$nginx" | cut -d' ' -f1)
before_id=$(sudo docker compose -p library-lab7-prod-app -f "$base/managed/prod/application/compose.yml" ps -q nginx)
sudo sed -i 's/worker_connections 1024/worker_connections 256/' "$nginx"
"${play[@]}"
after=$(sudo sha256sum "$nginx" | cut -d' ' -f1)
after_id=$(sudo docker compose -p library-lab7-prod-app -f "$base/managed/prod/application/compose.yml" ps -q nginx)
test "$before" = "$after"
test "$before_id" != "$after_id"
curl -fsS http://127.0.0.1:18082/health >/dev/null
# A second environment uses its own project names, ports, directories and volume.
"${play[@]}" -e lab_environment=staging -e lab_http_port=18083 -e lab_db_port=15543
curl -fsS http://127.0.0.1:18082/health >/dev/null
curl -fsS http://127.0.0.1:18083/health >/dev/null
