"""Smoke tests for the identity service's public surfaces (units 1-3)."""

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

User = get_user_model()

SIGNUP_PASSWORD = "resolute-amber-8"


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


class SignupRequiresVerificationTest(TestCase):
    """Email-only signup with mandatory verification (Q16)."""

    def test_signup_sends_verification_mail_and_blocks_login(self) -> None:
        # Arrange
        # Act
        response = self.client.post(
            reverse("account_signup"),
            {
                "email": "patient@example.com",
                "password1": SIGNUP_PASSWORD,
                "password2": SIGNUP_PASSWORD,
            },
        )

        # Assert
        # Mandatory verification: no session is opened after signup; the flow
        # lands on the verification-sent screen instead.
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"], reverse("account_email_verification_sent")
        )
        self.assertTrue(User.objects.filter(email="patient@example.com").exists())
        self.assertEqual(len(mail.outbox), 1)

        # An unverified account cannot log in: allauth refuses to open a
        # session and redirects to the email-verification screen instead.
        # Arrange
        # Act
        response = self.client.post(
            reverse("account_login"),
            {"login": "patient@example.com", "password": SIGNUP_PASSWORD},
        )

        # Assert
        self.assertEqual(
            response["Location"], reverse("account_email_verification_sent")
        )
        self.assertNotIn("_auth_user_id", self.client.session)
        response = self.client.get(reverse("token"))
        self.assertEqual(response.status_code, 401)
