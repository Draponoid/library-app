#!/usr/bin/env bash
# Restrict traffic to the published DB port, including after a Docker restart.
set -Eeuo pipefail
[[ $EUID == 0 && $# == 2 ]] || { echo 'Run as root with VM1_IP VM2_IP' >&2; exit 2; }
APP_IP=$1 DB_IP=$2
for ip in "$APP_IP" "$DB_IP"; do
  [[ $ip =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || exit 2
  IFS=. read -r a b c d <<< "$ip"
  for n in "$a" "$b" "$c" "$d"; do ((10#$n <= 255)) || exit 2; done
done
script=/usr/local/sbin/library-lab4-db-firewall
unit=/etc/systemd/system/library-lab4-db-firewall.service
[[ ! -e $script && ! -e $unit ]] || { echo 'Firewall files already exist; refusing to overwrite' >&2; exit 1; }
printf '%s\n' '#!/bin/sh' 'set -eu' \
  "iptables -C DOCKER-USER -p tcp -m conntrack --ctorigdst $DB_IP --ctorigdstport 5432 ! -s $APP_IP/32 -j DROP 2>/dev/null || iptables -I DOCKER-USER 1 -p tcp -m conntrack --ctorigdst $DB_IP --ctorigdstport 5432 ! -s $APP_IP/32 -j DROP" > "$script"
chmod 0755 "$script"
cat > "$unit" <<'EOF'
[Unit]
Description=Restrict library PostgreSQL access to VM1
Requires=docker.service
After=docker.service
PartOf=docker.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/library-lab4-db-firewall
RemainAfterExit=yes

[Install]
WantedBy=docker.service
EOF
systemctl daemon-reload
systemctl enable --now library-lab4-db-firewall.service
