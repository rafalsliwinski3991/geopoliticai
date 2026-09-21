"""Tests for the public landing page at `/` (unit 11)."""

import ast
from pathlib import Path

from django.test import SimpleTestCase
from django.urls import reverse

from pages.consts import LANDING_SECTIONS

_REPO_ROOT = Path(__file__).resolve().parents[3]
allow_list_path = _REPO_ROOT / "agentic_backend" / "src" / "agents" / "expert" / "consts" / "sources.py"


def canonical_allow_domains() -> frozenset[str]:
    """The expert's ALLOWED_DOMAINS, read by AST.

    web_backend may not import the agent package, so the drift guard parses
    the literal source instead: any change on either side fails one test.
    """
    tree = ast.parse(allow_list_path.read_text())
    for node in ast.walk(tree):
        targets: tuple[ast.expr, ...] = ()
        if isinstance(node, ast.AnnAssign):
            targets = (node.target,)
        elif isinstance(node, ast.Assign):
            targets = tuple(node.targets)
        if any(
            isinstance(target, ast.Name) and target.id == "ALLOWED_DOMAINS"
            for target in targets
        ):
            value = (
                node.value  # type: ignore[union-attr]
                if isinstance(node, ast.AnnAssign)
                else node.value  # type: ignore[union-attr]
            )
            return frozenset(ast.literal_eval(value))
    raise AssertionError("ALLOWED_DOMAINS not found in the expert's sources.py")


def advertised_daily_research_turns() -> int:
    """The DAILY_RESEARCH_TURNS literal, read by AST the same way."""
    path = _REPO_ROOT / "agentic_backend" / "src" / "config.py"
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "DAILY_RESEARCH_TURNS"
            for target in node.targets
        ):
            return ast.literal_eval(node.value)  # type: ignore[arg-type]
    raise AssertionError("DAILY_RESEARCH_TURNS not found in config.py")


class LandingPageTests(SimpleTestCase):
    """No models and no session use: the page renders without a database."""

    databases: list[str] = []

    def test_renders_200(self) -> None:
        # Arrange
        # Act
        response = self.client.get("/")
        # Assert
        self.assertEqual(response.status_code, 200)

    def test_links_to_the_chat_spa(self) -> None:
        # Arrange
        # Act
        response = self.client.get("/")
        # Assert
        self.assertContains(response, 'href="/chat"')

    def test_links_to_the_signup_screen(self) -> None:
        # Arrange
        # Act
        response = self.client.get("/")
        # Assert
        self.assertContains(response, 'href="/accounts/signup/"')

    def test_names_the_spectrum_bands(self) -> None:
        # Arrange
        # Act
        response = self.client.get("/")
        # Assert
        for heading in ("Left of center", "Center", "Right of center"):
            self.assertContains(response, heading)

    def test_every_allow_listed_domain_is_on_the_spectrum(self) -> None:
        """The copy is manual (§7: web_backend may not import the expert),
        so the drift guard checks the complete roster instead."""
        # Arrange
        # Act
        response = self.client.get("/")
        # Assert
        for domain in LANDING_SECTIONS.domains():
            self.assertContains(response, domain)

    def test_band_counts_match_their_lists(self) -> None:
        # Arrange
        # Act
        response = self.client.get("/")
        # Assert
        for band in LANDING_SECTIONS.bands:
            label = f'<span class="count">{len(band.domains)}</span>'
            self.assertContains(response, label)

    def test_the_roster_is_the_expert_allow_list_verbatim(self) -> None:
        """Set equality against the canonical AST-read allow-list, so a change
        to either side fails this guard instead of going public stale."""
        # Arrange
        # Act
        # Assert
        self.assertEqual(
            frozenset(LANDING_SECTIONS.domains()), canonical_allow_domains()
        )

    def test_the_advertised_daily_quota_is_the_enforced_value(self) -> None:
        """The landing copy's `20` must equal DAILY_RESEARCH_TURNS."""
        # Arrange
        # Act
        response = self.client.get("/")
        # Assert
        self.assertContains(
            response, f"{advertised_daily_research_turns()} research turns"
        )


class LandingRoutingTests(SimpleTestCase):
    # Arrange
    # Act
    def test_resolve_root(self) -> None:
        # Act
        resolved = reverse("pages:landing")
        # Assert
        self.assertEqual(resolved, "/")
