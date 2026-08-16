#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE="$ROOT/system_files/usr/lib/systemd/system/armada-flatpak-defaults.service"
SCRIPT="$ROOT/system_files/usr/libexec/armada/armada-flatpak-defaults"

[ -f "$SERVICE" ] || { echo "missing service: $SERVICE" >&2; exit 1; }
[ -f "$SCRIPT" ] || { echo "missing script: $SCRIPT" >&2; exit 1; }

grep -Fq 'After=network-online.target' "$SERVICE"
grep -Fq 'WantedBy=multi-user.target' "$SERVICE"
grep -Fq 'ConditionPathExists=!/var/lib/armada/.flatpak-initialized' "$SERVICE"
grep -Fq 'flatpak install --system -y --noninteractive flathub' "$SCRIPT"

echo "flatpak defaults service: present and network gated"
