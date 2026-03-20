#!/bin/sh
set -e

if [ -n "$AUTH_USER" ] && [ -n "$AUTH_PASSWORD" ]; then
    htpasswd -bc /etc/nginx/.htpasswd "$AUTH_USER" "$AUTH_PASSWORD"
    printf 'auth_basic "Restricted";\nauth_basic_user_file /etc/nginx/.htpasswd;\n' \
        > /etc/nginx/auth_snippet.conf
else
    # No credentials — disable auth
    printf '' > /etc/nginx/auth_snippet.conf
fi

exec "$@"
