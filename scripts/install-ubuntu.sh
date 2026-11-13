#!/usr/bin/env bash
# Install prerequisites non-interactively on a clean Ubuntu machine.
set -Eeuo pipefail
export DEBIAN_FRONTEND=noninteractive
sudo -n true
. /etc/os-release
if [[ ${ID:-} != ubuntu ]]; then echo 'Supported OS: Ubuntu' >&2; exit 1; fi
sudo -n apt-get update -qq
sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl git make openssl python3 iptables
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  sudo -n install -m 0755 -d /etc/apt/keyrings
  sudo -n curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  sudo -n chmod a+r /etc/apt/keyrings/docker.asc
  arch=$(dpkg --print-architecture)
  codename=${UBUNTU_CODENAME:-$VERSION_CODENAME}
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' "$arch" "$codename" | sudo -n tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo -n apt-get update -qq
  sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
sudo -n systemctl enable --now docker
sudo -n docker info >/dev/null
