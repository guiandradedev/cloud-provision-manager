#!/usr/bin/env bash

set -e

cat > /etc/systemd/system/concord-default-route.service <<'EOF'
[Unit]
Description=Use the Concord proxy as the default gateway
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'ip route del default via 10.0.2.2 2>/dev/null || true; ip route replace default via 10.20.30.1'
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

# O proxy também funciona como ponto de entrada para as consultas DNS.
rm -f /etc/resolv.conf
printf 'nameserver 10.20.30.1\n' > /etc/resolv.conf

systemctl daemon-reload
systemctl enable --now concord-default-route.service