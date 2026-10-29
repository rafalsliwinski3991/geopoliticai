"""Tests for the public landing page at `/` (unit 11)."""

import ast
import json
import re
from pathlib import Path

from django.test import SimpleTestCase
from django.urls import reverse
from django.utils.html import escape
from django.utils.text import capfirst

from pages.consts import FORECASTERS, LANDING_SECTIONS

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


def canonical_forecasters() -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """The deep forecaster's FORECASTERS as (name, focus, domains), read by AST."""
    path = (
        _REPO_ROOT
        / "agentic_backend"
        / "src"
        / "agents"
        / "deep_forecaster"
        / "consts"
        / "forecasters.py"
    )
    tree = ast.parse(path.read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Forecaster"
    ]
    rows = [tuple(ast.literal_eval(arg) for arg in call.args) for call in calls]
    return tuple((row[1], row[3], row[5]) for row in rows)


def advertised_daily_research_turns() -> int:
    """The DAILY_RESEARCH_TURNS literal, read by AST the same way."""
    path = _REPO_ROOT / "agentic_backend" / "src" / "shared" / "config.py"
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

    def test_the_forecaster_roster_is_the_deep_forecaster_list_verbatim(self) -> None:
        # Arrange
        expected = canonical_forecasters()
        # Act
        actual = tuple((f["name"], f["focus"], f["domains"]) for f in FORECASTERS)
        # Assert
        self.assertEqual(actual, expected)

    def test_every_forecaster_is_shown_on_the_page(self) -> None:
        # Arrange
        # Act
        response = self.client.get("/")
        # Assert
        for forecaster in FORECASTERS:
            self.assertContains(response, forecaster["name"])
            self.assertContains(response, escape(capfirst(forecaster["focus"])))
            for domain in forecaster["domains"]:
                self.assertContains(response, domain)

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


class LandingMetadataTests(SimpleTestCase):
    """The head is built from settings, not the DB — this file stays
    SimpleTestCase to guard that (plan §1, code-wins note 1)."""

    def test_the_canonical_link_is_the_production_origin(self) -> None:
        # Arrange
        # Act
        response = self.client.get("/")

        # Assert
        self.assertContains(
            response, '<link rel="canonical" href="https://politicalagent.eu/">'
        )

    def test_the_default_description_is_within_160_characters(self) -> None:
        # Arrange
        # Act
        response = self.client.get("/")
        html = response.content.decode()
        match = re.search(r'<meta name="description" content="([^"]*)"', html)

        # Assert
        self.assertIsNotNone(match)
        self.assertLessEqual(len(match.group(1)), 160)

    def test_the_og_image_is_the_share_card(self) -> None:
        # Arrange
        # Act
        response = self.client.get("/")
        html = response.content.decode()
        match = re.search(r'<meta property="og:image" content="([^"]*)"', html)

        # Assert
        self.assertIsNotNone(match)
        self.assertTrue(match.group(1).endswith(".png"), match.group(1))

    def test_the_landing_jsonld_graph_names_the_organization_and_website(self) -> None:
        # Arrange
        # Act
        response = self.client.get("/")
        html = response.content.decode()
        match = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)

        # Assert
        self.assertIsNotNone(match)
        payload = json.loads(match.group(1))
        self.assertEqual(
            {node["@type"] for node in payload["@graph"]}, {"Organization", "WebSite"}
        )

    def test_the_hero_kicker_describes_english_and_polish_research(self) -> None:
        # Arrange
        # Act
        response = self.client.get("/")

        # Assert
        self.assertContains(
            response,
            "Geopolitical research, in English and Polish, one question at a time",
        )

    def test_the_limits_card_names_the_two_languages(self) -> None:
        # Arrange
        # Act
        response = self.client.get("/")

        # Assert
        self.assertContains(response, "<h3>Work in English and Polish only</h3>")

    def test_the_limits_card_states_the_english_refusal(self) -> None:
        # Arrange
        # Act
        response = self.client.get("/")

        # Assert
        self.assertContains(
            response,
            "a message in any other language gets a short refusal in English.",
        )

    def test_the_limits_card_drops_the_english_only_sentence(self) -> None:
        # Arrange
        # Act
        response = self.client.get("/")

        # Assert
        self.assertNotContains(response, "Questions and answers are English.")

    def test_the_limits_describe_the_opt_in_forecast(self) -> None:
        # Arrange
        # Act
        response = self.client.get("/")
        # Assert
        self.assertContains(response, "Forecast unless you ask")
        self.assertContains(response, "says so in its answer")
        self.assertNotContains(response, "does not forecast elections or wars")
