"""The `sites` row must point at the public host (unit 05)."""

from __future__ import annotations

from django.conf import settings
from django.contrib.sites.models import Site
from django.test import TestCase


class SiteDomainTests(TestCase):
    def test_the_sites_row_carries_the_production_domain(self) -> None:
        # Arrange
        # Act
        site = Site.objects.get(id=settings.SITE_ID)

        # Assert
        self.assertEqual(site.domain, "politicalagent.eu")
        self.assertEqual(site.name, "PoliticalAgent")
