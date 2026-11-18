#!/bin/sh
# One-time setup of a hosted team explorer, run as root on the server (Ubuntu with nginx):
#
#   scp scripts/explorer-server-setup.sh <host>:   then   ssh -t <host> sudo sh explorer-server-setup.sh <user> [path]
#
# It makes <path> (default /srv/explorer) owned by <user>, so later deploys
# (`social-energy deploy-explorer`) and login changes (`social-energy explorer-user`) need no
# admin rights; it makes an empty login list readable by nginx and nobody else; and it replaces
# the default nginx site with one that serves <path>/current over HTTPS behind those logins,
# redirecting plain HTTP. The certificate stays the server's own (snakeoil) until the institute
# issues one. See docs/decisions/explorer-hosted.md.
set -eu
user=${1:?usage: explorer-server-setup.sh <user> [path]}
path=${2:-/srv/explorer}
id "$user" >/dev/null

install -d -o "$user" -g "$user" -m 755 "$path"
[ -e "$path/htpasswd" ] || install -o "$user" -g www-data -m 640 /dev/null "$path/htpasswd"
chgrp www-data "$path/htpasswd"
chmod 640 "$path/htpasswd"

site=/etc/nginx/sites-available/explorer
cat > "$site" <<EOF
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
    auth_basic "Social Energy Explorer";
    auth_basic_user_file $path/htpasswd;
    add_header Cache-Control "no-store" always;
    add_header X-Robots-Tag "noindex, nofollow" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "no-referrer" always;
    location / {
        try_files \$uri \$uri/ =404;
    }
}
EOF
for old in /etc/nginx/sites-enabled/*; do
    [ "$old" = /etc/nginx/sites-enabled/explorer ] || mv "$old" "/etc/nginx/disabled-$(basename "$old")"
done
ln -sf "$site" /etc/nginx/sites-enabled/explorer
nginx -t
systemctl reload nginx
echo "Explorer site ready: serves $path/current, logins in $path/htpasswd (owned by $user)."
