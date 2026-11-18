#!/bin/sh
# One-time setup of a hosted team explorer, run as root on the server (Ubuntu with nginx):
#
#   ssh <host> 'cat > explorer-server-setup.sh' < scripts/explorer-server-setup.sh
#   ssh -t <host> sudo sh explorer-server-setup.sh <user> [path]
#
# Run a deploy first (`social-energy deploy-explorer`): it puts the app in <path>/current and the
# sign-in service in <path>/service. This script makes <path> (default /srv/explorer) owned by
# <user>, so later deploys need no admin rights; runs the sign-in service as <user> under systemd
# (127.0.0.1:8790, restarting itself when a deploy replaces it); and replaces the default nginx
# site with one that serves <path>/current over HTTPS only to signed-in researchers, asking the
# service about every request. Safe to run again. The certificate stays the server's own
# (snakeoil) until the institute issues one. See docs/decisions/explorer-hosted.md.
set -eu
user=${1:?usage: explorer-server-setup.sh <user> [path]}
path=${2:-/srv/explorer}
id "$user" >/dev/null

install -d -o "$user" -g "$user" -m 755 "$path"
if [ ! -f "$path/service/auth_service.py" ]; then
    echo "Deploy first: there is no $path/service/auth_service.py" >&2
    exit 1
fi
rm -f "$path/htpasswd"   # the first version's basic-auth logins, replaced by the service

cat > /etc/systemd/system/explorer-auth.service <<UNIT
[Unit]
Description=Sign-in service of the team explorer (social-energy-education)
After=network.target

[Service]
User=$user
ExecStart=/usr/bin/python3 $path/service/auth_service.py serve --db $path/auth.db --port 8790
Restart=always
RestartSec=2
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=$path
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable explorer-auth.service
systemctl restart explorer-auth.service

site=/etc/nginx/sites-available/explorer
cat > "$site" <<SITE
# The team explorer (social-energy-education). Written by explorer-server-setup.sh.
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    return 301 https://\$host\$request_uri;
}
server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    include snippets/snakeoil.conf;
    server_name _;
    root $path/current;
    index index.html;
    add_header Cache-Control "no-store" always;
    add_header X-Robots-Tag "noindex, nofollow" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "no-referrer" always;
    add_header X-Frame-Options "DENY" always;

    # Every page of the explorer needs a signed-in session; without one, the sign-in page.
    auth_request /_check;
    error_page 401 = @signin;
    location = /_check {
        internal;
        proxy_pass http://127.0.0.1:8790/check;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
        proxy_set_header Cookie \$http_cookie;
    }
    location @signin {
        return 302 /auth/login?next=\$request_uri;
    }
    location /auth/ {
        auth_request off;
        proxy_pass http://127.0.0.1:8790;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
    location / {
        try_files \$uri \$uri/ =404;
    }
}
SITE
for old in /etc/nginx/sites-enabled/*; do
    [ "$old" = /etc/nginx/sites-enabled/explorer ] || mv "$old" "/etc/nginx/disabled-$(basename "$old")"
done
ln -sf "$site" /etc/nginx/sites-enabled/explorer
nginx -t
systemctl reload nginx
sleep 1
systemctl is-active explorer-auth.service
echo "Explorer site ready: serves $path/current to signed-in researchers; users in $path/auth.db."
