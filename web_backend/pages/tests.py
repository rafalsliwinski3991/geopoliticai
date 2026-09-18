"""Tests for the public landing page at `/`."""

from django.test import SimpleTestCase
from django.urls import reverse

from pages.consts import LANDING_SECTIONS


class LandingPageTests(SimpleTestCase):
    """No models and no session use: the page renders without a database."""

    databases: list[str] = []

    def test_renders_200(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_links_to_the_chat_spa(self) -> None:
        response = self.client.get("/")
        self.assertContains(response, 'href="/chat"')

    def test_links_to_the_signup_screen(self) -> None:
        response = self.client.get("/")
        self.assertContains(response, 'href="/accounts/signup/"')

    def test_names_the_spectrum_bands(self) -> None:
        response = self.client.get("/")
        for heading in ("Left of center", "Center", "Right of center"):
            self.assertContains(response, heading)

    def test_every_allow_listed_domain_is_on_the_spectrum(self) -> None:
        """The copy is manual (§7: web_backend may not import the expert),
        so the drift guard checks the complete roster instead."""
        response = self.client.get("/")
        for domain in LANDING_SECTIONS.domains():
            self.assertContains(response, domain)

    def test_band_counts_match_their_lists(self) -> None:
        response = self.client.get("/")
        for band in LANDING_SECTIONS.bands:
            label = f'<span class="count">{len(band.domains)}</span>'
            self.assertContains(response, label)


class LandingRoutingTests(SimpleTestCase):
    def test_resolve_root(self) -> None:
        self.assertEqual(reverse("pages:landing"), "/")
