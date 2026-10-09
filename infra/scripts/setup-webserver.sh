#!/usr/bin/env bash

set -e

export DEBIAN_FRONTEND=noninteractive

apt-get update -y

curl -fsSL https://deb.nodesource.com/setup_24.x | bash -

# iptables-persistent asks whether the current rules should be saved while its
# post-install script runs. Preseed both answers so provisioning never blocks.
echo 'iptables-persistent iptables-persistent/autosave_v4 boolean false' | debconf-set-selections
echo 'iptables-persistent iptables-persistent/autosave_v6 boolean false' | debconf-set-selections
apt-get install -y python3 python3-pip python3-venv nginx iptables-persistent nodejs

cat > /etc/sysctl.d/99-provision-manager-gateway.conf <<'EOF'
net.ipv4.ip_forward=1
EOF

sysctl -p /etc/sysctl.d/99-provision-manager-gateway.conf

WAN_IF=$(ip route show default | awk '{print $5; exit}')

# Encaminha o DNS recebido em 10.20.30.1 para o DNS do NAT do VirtualBox.
iptables -t nat -C PREROUTING -d 10.20.30.1 -p udp --dport 53 -j DNAT --to-destination 10.0.2.3 2>/dev/null || \
    iptables -t nat -A PREROUTING -d 10.20.30.1 -p udp --dport 53 -j DNAT --to-destination 10.0.2.3
iptables -t nat -C PREROUTING -d 10.20.30.1 -p tcp --dport 53 -j DNAT --to-destination 10.0.2.3 2>/dev/null || \
    iptables -t nat -A PREROUTING -d 10.20.30.1 -p tcp --dport 53 -j DNAT --to-destination 10.0.2.3

iptables -t nat -C POSTROUTING -s 10.20.30.0/28 -o "$WAN_IF" -j MASQUERADE 2>/dev/null || \
    iptables -t nat -A POSTROUTING -s 10.20.30.0/28 -o "$WAN_IF" -j MASQUERADE
iptables -C FORWARD -s 10.20.30.0/28 -o "$WAN_IF" -j ACCEPT 2>/dev/null || \
    iptables -I FORWARD 1 -s 10.20.30.0/28 -o "$WAN_IF" -j ACCEPT
iptables -C FORWARD -d 10.20.30.0/28 -i "$WAN_IF" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || \
    iptables -I FORWARD 1 -d 10.20.30.0/28 -i "$WAN_IF" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
netfilter-persistent save

cd /home/application/provision-manager/frontend

cat <<'EOF' > .env.production
VITE_BACKEND_URL=/api
VITE_REALTIME_GATEWAY_URL=http://localhost:8069
EOF

npm ci
npm run build

cat <<'EOT' > /etc/systemd/system/provision-manager-frontend.service
[Unit]
Description=CPM Frontend
After=network.target

[Service]
User=root
WorkingDirectory=/home/application/provision-manager/frontend
Environment=NODE_ENV=production
ExecStart=/usr/bin/npm run start
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOT

cat > /etc/nginx/sites-available/provision-manager <<'EOF'
server {
    listen 80;
    server_name _;

    location /api/ {
        proxy_pass http://127.0.0.1:8082/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

ln -sf /etc/nginx/sites-available/provision-manager /etc/nginx/sites-enabled/provision-manager
rm -f /etc/nginx/sites-enabled/default

cd /home/application/provision-manager/backend

python3 -m venv venv

./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

cat > /etc/systemd/system/provision-manager-backend.service <<EOT
[Unit]
Description=Provision Manager API
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/home/application/provision-manager/backend
Environment="DATABASE_URL=mysql+aiomysql://${DB_USER}:${DB_PASS}@10.20.30.3:3306/mydb"
ExecStartPre=/bin/sh -c 'until nc -z 10.20.30.3 3306; do sleep 2; done'
TimeoutStartSec=infinity
ExecStart=/home/application/provision-manager/backend/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8082
SuccessExitStatus=143
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOT

systemctl daemon-reload
systemctl enable provision-manager-backend
systemctl start --no-block provision-manager-backend
systemctl enable --now provision-manager-frontend

systemctl restart nginx