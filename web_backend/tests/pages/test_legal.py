"""Tests for /about/ and /privacy/ (unit 06).

The literals are asserted deliberately (not the OPERATOR constant), so a
later edit to the constant has to update a test deliberately.
"""

from __future__ import annotations

from django.test import TestCase
from django.urls import reverse


class AboutPageTests(TestCase):
    def test_about_renders_the_operator_identity(self) -> None:
        # Arrange
        # Act
        response = self.client.get("/about/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rafal Sliwinski")
        self.assertContains(response, "21-040 Swidnik")
        self.assertContains(response, "contact@politicalagent.eu")
        self.assertContains(
            response,
            '<meta name="description" content="Who runs PoliticalAgent, how to contact us, '
            'and how the AI-generated blog is published and corrected.">',
            html=True,
        )


class PrivacyPageTests(TestCase):
    def test_privacy_renders_the_controller_and_the_recipients(self) -> None:
        # Arrange
        # Act
        response = self.client.get("/privacy/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rafal Sliwinski")
        self.assertContains(response, "21-040 Swidnik")
        self.assertContains(response, "contact@politicalagent.eu")
        self.assertContains(response, "OpenAI")
        self.assertContains(response, "Brave")
        self.assertContains(response, "OVHcloud")
        self.assertContains(response, "blog@politicalagent.eu")
        self.assertContains(
            response,
            '<meta name="description" content="What personal data PoliticalAgent processes, '
            'why, for how long, who receives it, and your rights under the GDPR.">',
            html=True,
        )
        self.assertContains(response, "Last updated 24 September 2026.")
        self.assertContains(response, "uodo.gov.pl")


class LegalLinkingTests(TestCase):
    def test_the_footer_links_both_legal_pages(self) -> None:
        # Arrange
        # Act
        response = self.client.get("/")

        # Assert
        self.assertContains(response, 'href="/about/"')
        self.assertContains(response, 'href="/privacy/"')

    def test_the_signup_page_links_the_privacy_notice(self) -> None:
        # Arrange
        # Act
        response = self.client.get("/accounts/signup/")

        # Assert
        self.assertContains(response, 'href="/privacy/"')

    def test_the_sitemap_lists_both_legal_pages(self) -> None:
        # Arrange
        # Act
        response = self.client.get("/sitemap.xml", secure=True)

        # Assert
        body = response.content.decode()
        self.assertIn("https://politicalagent.eu/about/", body)
        self.assertIn("https://politicalagent.eu/privacy/", body)
