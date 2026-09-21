"""Tests for the session-cookie to JWT exchange (unit 3)."""

import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()

PASSWORD = "resolute-amber-8"


class TokenViewTest(TestCase):
    """GET /accounts/token/ is a JSON endpoint for the SPA, never a redirect."""

    def test_anonymous_gets_json_401_not_a_redirect(self) -> None:
        response = self.client.get(reverse("token"))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertIn("detail", response.json())

    def test_logged_in_gets_a_decodable_access_token(self) -> None:
        user = User.objects.create_user(email="researcher@example.com", password=PASSWORD)
        self.client.force_login(user)
        response = self.client.get(reverse("token"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("access", data)
        self.assertEqual(data["expires_in"], settings.ACCESS_TOKEN_SECONDS)
        claims = jwt.decode(
            data["access"],
            settings.SIMPLE_JWT["SIGNING_KEY"],
            algorithms=["HS256"],
        )
        # simplejwt stringifies the id in Token.for_user unconditionally.
        self.assertEqual(claims["user_id"], str(user.pk))
        self.assertEqual(claims["token_type"], "access")

    def test_inactive_user_gets_401(self) -> None:
        user = User.objects.create_user(
            email="inactive@example.com", password=PASSWORD, is_active=False
        )
        self.client.force_login(user)
        response = self.client.get(reverse("token"))
        self.assertEqual(response.status_code, 401)
