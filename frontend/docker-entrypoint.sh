#!/bin/sh
set -e

if [ "${AUTH_REQUIRED:-false}" = "true" ] && {
    [ -z "${AUTH_USER:-}" ] || [ -z "${AUTH_PASSWORD:-}" ];
}; then
    printf '%s\n' 'AUTH_REQUIRED=true requires both AUTH_USER and AUTH_PASSWORD' >&2
    printf '%s\n' '(they guard the /admin/ and /phoenix/ surfaces; the API uses JWTs)' >&2
    exit 1
fi

if [ -n "${AUTH_USER:-}" ] && [ -n "${AUTH_PASSWORD:-}" ]; then
    htpasswd -bc /etc/nginx/.htpasswd "$AUTH_USER" "$AUTH_PASSWORD"
    printf 'auth_basic "Restricted";\nauth_basic_user_file /etc/nginx/.htpasswd;\n' \
        > /etc/nginx/auth_snippet.conf
else
    # Authentication is intentionally disabled for local development.
    # In production this leaves /admin/ and /phoenix/ unguarded until
    # AUTH_USER and AUTH_PASSWORD are set — the only locations that
    # include the snippet.
    printf '' > /etc/nginx/auth_snippet.conf
fi

exec "$@"
