"""Smoke tests for the identity service's public surfaces (units 1-3)."""

import os
import subprocess
import sys
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

User = get_user_model()

SIGNUP_PASSWORD = "resolute-amber-8"


def nginx_servers() -> list[str]:
    """Return each top-level `server { ... }` block of frontend/nginx.conf as text."""
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "frontend" / "nginx.conf"
    return ["server {" + part for part in path.read_text().split("server {")[1:]]


class AuthScreensTest(TestCase):
    """The allauth screens and the admin login gate respond as routes, not 500s."""

    WORDMARK = "Political<em>Agent</em>"
    # Manifest storage hashes the filename; the prefix stays stable.
    STYLESHEET = "site/style."

    def assert_branded(self, url_name: str) -> None:
        # Arrange
        # Act
        response = self.client.get(reverse(url_name))

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.WORDMARK)
        self.assertContains(response, self.STYLESHEET)

    def test_login_page_renders(self) -> None:
        self.assert_branded("account_login")

    def test_signup_page_renders(self) -> None:
        self.assert_branded("account_signup")

    def test_password_reset_page_renders(self) -> None:
        self.assert_branded("account_reset_password")

    def test_verification_sent_page_renders(self) -> None:
        self.assert_branded("account_email_verification_sent")

    def test_admin_redirects_anonymous_users_to_login(self) -> None:
        # Arrange
        # Act
        response = self.client.get("/admin/")

        # Assert
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])


class SignupOpensSessionTest(TestCase):
    """Email and one password open a session at once, with no verification mail."""

    def test_signup_logs_in_and_mints_a_token_without_mail(self) -> None:
        # Arrange
        # Act
        response = self.client.post(
            reverse("account_signup"),
            {"email": "patient@example.com", "password1": SIGNUP_PASSWORD},
        )

        # Assert
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/chat")
        user = User.objects.get(email="patient@example.com")
        self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(self.client.get(reverse("token")).status_code, 200)

    def test_signup_form_asks_for_the_password_once(self) -> None:
        # Arrange
        # Act
        response = self.client.get(reverse("account_signup"))

        # Assert
        self.assertContains(response, 'name="password1"')
        self.assertNotContains(response, 'name="password2"')


class NginxAdminGuardTest(TestCase):
    """The nginx guard on `/admin/` has to outlive every unit that edits nginx.

    This test lives in the Django suite on purpose: unit 9 deletes
    `frontend/tests/` and its CI job, and unit 11 rewrites the same server
    block. `/admin/` reads any user's conversations; the assertion must
    survive all of it.
    """

    def locations(self) -> dict[str, str]:
        from pathlib import Path

        path = Path(__file__).resolve().parents[3] / "frontend" / "nginx.conf"
        text = path.read_text()
        locations: dict[str, str] = {}
        for block in text.split("location ")[1:]:
            name, _, body = block.partition("{")
            locations[name.strip().split()[0]] = body.split("}")[0]
        return locations

    def test_auth_snippet_guards_the_admin_and_phoenix_surfaces(self) -> None:
        for name, body in self.locations().items():
            if name in ("/admin/", "/phoenix/"):
                self.assertIn("auth_snippet.conf", body)
            else:
                self.assertNotIn("auth_snippet.conf", body)

    def test_the_admin_location_proxies_to_the_identity_service(self) -> None:
        self.assertIn("web-backend:8000", self.locations()["/admin/"])

    def test_the_phoenix_location_strips_its_prefix_and_upgrades(self) -> None:
        body = self.locations()["/phoenix/"]
        self.assertIn("set $phoenix http://phoenix:6006;", body)
        self.assertIn("proxy_pass $phoenix;", body)
        self.assertIn("rewrite ^/phoenix/(.*)$ /$1 break;", body)
        self.assertIn("proxy_set_header Upgrade $http_upgrade;", body)
        self.assertIn("proxy_set_header Connection $http_connection;", body)


class NginxSeoTest(TestCase):
    """Search engines must see one host and an indexable-free chat shell.

    Unit 08 restructures nginx.conf into three server blocks; these
    assertions use the server-block parser, which the `locations()` parser
    below lacks server-awareness for.
    """

    def test_exactly_one_www_tls_block_redirects_to_the_apex(self) -> None:
        # Arrange
        # Act
        blocks = [b for b in nginx_servers() if "server_name www.politicalagent.eu;" in b]

        # Assert
        self.assertEqual(len(blocks), 1)
        self.assertIn("listen 443 ssl;", blocks[0])
        self.assertIn("return 301 https://politicalagent.eu$request_uri;", blocks[0])

    def test_the_port_80_block_redirects_to_the_apex_and_keeps_certbot(self) -> None:
        # Arrange
        # Act
        blocks = [b for b in nginx_servers() if "listen 80;" in b]

        # Assert
        self.assertEqual(len(blocks), 1)
        self.assertIn("return 301 https://politicalagent.eu$request_uri;", blocks[0])
        self.assertIn("/.well-known/acme-challenge/", blocks[0])

    def test_the_apex_tls_block_serves_only_the_apex_name(self) -> None:
        # Arrange
        # Act
        blocks = [
            b
            for b in nginx_servers()
            if "listen 443 ssl;" in b and "server_name politicalagent.eu;" in b
        ]

        # Assert
        self.assertEqual(len(blocks), 1)
        self.assertNotIn("www", blocks[0])

    def test_the_chat_location_carries_the_noindex_header(self) -> None:
        # Arrange
        # Act
        body = NginxAdminGuardTest().locations()["/chat"]

        # Assert
        self.assertIn('X-Robots-Tag "noindex"', body)
        self.assertIn("try_files", body)


class NginxHstsTest(TestCase):
    """Every HTTPS response carries exactly one HSTS header, set by nginx."""

    HSTS = 'add_header Strict-Transport-Security "max-age=31536000" always;'

    def test_both_tls_server_blocks_set_hsts_at_server_level(self) -> None:
        # Arrange
        # Act
        blocks = [b for b in nginx_servers() if "listen 443 ssl;" in b]

        # Assert
        self.assertEqual(len(blocks), 2)
        for block in blocks:
            self.assertIn(self.HSTS, block.split("location ")[0])

    def test_locations_with_their_own_add_header_repeat_hsts(self) -> None:
        # Arrange
        # Act
        overriding = {
            name: body
            for name, body in NginxAdminGuardTest().locations().items()
            if "add_header" in body
        }

        # Assert
        self.assertIn("/chat", overriding)
        for body in overriding.values():
            self.assertIn(self.HSTS, body)

    def test_proxied_locations_drop_the_upstream_hsts_header(self) -> None:
        # Arrange
        frontend = Path(__file__).resolve().parents[3] / "frontend"

        # Act
        proxied = [b for b in NginxAdminGuardTest().locations().values() if "proxy_pass" in b]

        # Assert
        self.assertIn(
            "proxy_hide_header Strict-Transport-Security;",
            (frontend / "proxy_common.conf").read_text(),
        )
        for body in proxied:
            self.assertIn("include /etc/nginx/proxy_common.conf;", body)


class HstsSettingsTest(TestCase):
    def _hsts_seconds(self, debug: str) -> int:
        web_backend = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [sys.executable, "-c", "import politicalagent.settings as s; print(s.SECURE_HSTS_SECONDS)"],
            cwd=web_backend,
            env={**os.environ, "DJANGO_DEBUG": debug},
            capture_output=True,
            text=True,
            check=True,
        )
        return int(result.stdout)

    def test_hsts_is_a_year_in_production_and_off_in_debug(self) -> None:
        # Arrange
        # Act
        # Assert
        self.assertEqual(self._hsts_seconds("false"), 31536000)
        self.assertEqual(self._hsts_seconds("true"), 0)
