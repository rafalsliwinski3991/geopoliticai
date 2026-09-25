"""Static-asset guards for the public site (units 03-04).

Unit 03 keeps every font self-hosted under `/static/site/fonts/` (render
blocking + GDPR: LG München 3 O 17493/20). Unit 04 adds the share-image
dimension guards.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import TestCase

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FONTS_DIR = _REPO_ROOT / "web_backend" / "static" / "site" / "fonts"


def read_repo_file(relative: str) -> str:
    return (_REPO_ROOT / relative).read_text()


class SelfHostedFontsTests(TestCase):
    def test_no_google_fonts_in_any_stylesheet(self) -> None:
        # Arrange
        stylesheets = (
            "web_backend/static/site/style.css",
            "web_backend/static/site/fonts.css",
            "frontend/chat/src/chat.css",
            "frontend/chat/src/fonts.css",
        )

        # Act
        # Assert
        for relative in stylesheets:
            text = read_repo_file(relative)
            self.assertNotIn("fonts.googleapis.com", text, relative)
            self.assertNotIn("fonts.gstatic.com", text, relative)

    def test_every_font_url_in_fonts_css_resolves_to_a_file(self) -> None:
        # Arrange
        text = read_repo_file("web_backend/static/site/fonts.css")

        # Act
        urls = re.findall(r'url\("([^"]+)"\)', text)

        # Assert
        self.assertTrue(urls)
        for url in urls:
            self.assertTrue(
                (_REPO_ROOT / "web_backend" / "static" / "site" / url).is_file(), url
            )

    def test_the_spa_fonts_css_mirrors_the_site_one_with_absolute_urls(self) -> None:
        # Arrange
        site = read_repo_file("web_backend/static/site/fonts.css")
        spa = read_repo_file("frontend/chat/src/fonts.css")

        # Act
        urls = re.findall(r'url\("([^"]+)"\)', spa)

        # Assert
        self.assertTrue(urls)
        for url in urls:
            self.assertTrue(url.startswith("/static/site/fonts/"), url)
            self.assertTrue((_REPO_ROOT / "web_backend" / url.lstrip("/")).is_file(), url)
        self.assertEqual(spa, site.replace('url("fonts/', 'url("/static/site/fonts/'))

    def test_the_three_font_licences_ship_with_the_fonts(self) -> None:
        # Arrange
        licences = (
            "OFL-ibmplexsans.txt",
            "OFL-ibmplexsanscondensed.txt",
            "OFL-spectral.txt",
        )

        # Act
        # Assert
        for name in licences:
            self.assertTrue((_FONTS_DIR / name).is_file(), name)
