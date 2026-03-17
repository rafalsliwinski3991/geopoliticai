#!/bin/sh
set -e

if [ -n "$AUTH_USER" ] && [ -n "$AUTH_PASSWORD" ]; then
    htpasswd -bc /etc/nginx/.htpasswd "$AUTH_USER" "$AUTH_PASSWORD"
else
    # No credentials set — create an empty file so nginx doesn't error
    touch /etc/nginx/.htpasswd
fi

exec "$@"
