#!/usr/bin/env sh
set -eu

# Certbot invokes this only after a certificate has renewed successfully.
/usr/sbin/nginx -t
/usr/bin/systemctl reload nginx
