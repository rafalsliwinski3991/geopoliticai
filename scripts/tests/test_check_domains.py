"""Unit tests for the domain checking script."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.response
from typing import Any
from unittest.mock import MagicMock

import pytest

from other import check_domains

SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Global Security &amp; Strategy</title>
    <style>.nav { display: none; }</style>
</head>
<body>
    <script>var x = 1;</script>
    <h1>Global Security</h1>
    <p>This is a detailed policy analysis discussing regional geopolitical shifts and alliances.</p>
    <p>Multiple paragraphs ensure that the extracted text length exceeds the required threshold.</p>
    <p>Comprehensive coverage of disarmament, defense budgets, and international security cooperation.</p>
    <a href="/research/2026/global-spending">2026 Spending Report</a>
    <a href="/about-us">About Us</a>
    <a href="/logo.png">Logo</a>
</body>
</html>
"""

BOT_CHALLENGE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Just a moment...</title></head>
<body>
<div class="cf-challenge">Please verify you are a human</div>
</body>
</html>
"""


def _make_mock_response(
    status: int = 200,
    body: str = SAMPLE_HTML,
    url: str = "https://example.org/",
    content_type: str = "text/html; charset=utf-8",
) -> MagicMock:
    raw_bytes = body.encode("utf-8")
    resp = MagicMock()
    resp.status = status
    resp.geturl.return_value = url
    resp.headers = {"content-type": content_type}
    resp.read.side_effect = [raw_bytes, b""]
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = None
    return resp


def test_clean_html_text_removes_scripts_styles_and_tags() -> None:
    # Arrange
    raw_html = (
        "<html><head><style>p{color:red;}</style></head><body><script>alert(1);</script>"
        "<h1>Hello</h1> <p>World &amp; Peace</p></body></html>"
    )

    # Act
    cleaned = check_domains.clean_html_text(raw_html)

    # Assert
    assert cleaned == "Hello World &amp; Peace"


def test_extract_title_reads_and_unescapes_title() -> None:
    # Arrange
    raw_html = "<html><head><title>  Foreign Policy &amp; Affairs  </title></head></html>"

    # Act
    title = check_domains.extract_title(raw_html)

    # Assert
    assert title == "Foreign Policy & Affairs"


def test_extract_title_returns_empty_when_no_title() -> None:
    # Arrange
    raw_html = "<html><head></head><body>Hello</body></html>"

    # Act
    title = check_domains.extract_title(raw_html)

    # Assert
    assert title == ""


def test_find_article_links_extracts_internal_links_and_filters_static() -> None:
    # Arrange
    base_url = "https://example.org/"
    domain = "example.org"

    # Act
    links = check_domains.find_article_links(SAMPLE_HTML, base_url, domain)

    # Assert
    assert "https://example.org/research/2026/global-spending" in links
    assert not any(link.endswith(".png") for link in links)


def test_probe_domain_returns_blocked_on_403_homepage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    def fake_urlopen(*args: Any, **kwargs: Any) -> Any:
        fp = io.BytesIO(b"Access Denied")
        raise urllib.error.HTTPError(
            url="https://blocked.com",
            code=403,
            msg="Forbidden",
            hdrs=None,  # type: ignore[arg-type]
            fp=fp,
        )

    monkeypatch.setattr(check_domains.urllib.request, "urlopen", fake_urlopen)

    # Act
    result = check_domains.probe_domain("blocked.com", check_article=False)

    # Assert
    assert result.outcome == "BLOCKED"
    assert result.home_status == 403
    assert "Homepage blocked" in result.reason


def test_probe_domain_returns_blocked_on_401_homepage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    def fake_urlopen(*args: Any, **kwargs: Any) -> Any:
        fp = io.BytesIO(b"Unauthorized")
        raise urllib.error.HTTPError(
            url="https://paywalled.com",
            code=401,
            msg="Unauthorized",
            hdrs=None,  # type: ignore[arg-type]
            fp=fp,
        )

    monkeypatch.setattr(check_domains.urllib.request, "urlopen", fake_urlopen)

    # Act
    result = check_domains.probe_domain("paywalled.com", check_article=False)

    # Assert
    assert result.outcome == "BLOCKED"
    assert result.home_status == 401


def test_probe_domain_returns_blocked_on_bot_challenge_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    mock_resp = _make_mock_response(status=200, body=BOT_CHALLENGE_HTML)
    monkeypatch.setattr(
        check_domains.urllib.request, "urlopen", lambda *a, **k: mock_resp
    )

    # Act
    result = check_domains.probe_domain("challenge.org", check_article=False)

    # Assert
    assert result.outcome == "BLOCKED"
    assert "Bot challenge" in result.reason


def test_probe_domain_returns_blocked_when_article_returns_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    home_resp = _make_mock_response(status=200, body=SAMPLE_HTML)

    def fake_urlopen(req: Any, *args: Any, **kwargs: Any) -> Any:
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "research" in url:
            fp = io.BytesIO(b"Forbidden")
            raise urllib.error.HTTPError(
                url=url,
                code=403,
                msg="Forbidden",
                hdrs=None,  # type: ignore[arg-type]
                fp=fp,
            )
        return home_resp

    monkeypatch.setattr(check_domains.urllib.request, "urlopen", fake_urlopen)

    # Act
    result = check_domains.probe_domain("example.org", check_article=True)

    # Assert
    assert result.outcome == "BLOCKED"
    assert result.home_status == 200
    assert result.article_status == 403
    assert "Article blocked" in result.reason


def test_probe_domain_returns_available_on_working_homepage_and_article(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    mock_resp = _make_mock_response(status=200, body=SAMPLE_HTML)
    monkeypatch.setattr(
        check_domains.urllib.request, "urlopen", lambda *a, **k: mock_resp
    )

    # Act
    result = check_domains.probe_domain("example.org", check_article=True)

    # Assert
    assert result.outcome == "AVAILABLE"
    assert result.home_status == 200
    assert result.article_status == 200
    assert result.title == "Global Security & Strategy"


def test_probe_domain_returns_unreadable_when_text_too_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    short_html = "<html><head><title>Shell</title></head><body>Loading...</body></html>"
    mock_resp = _make_mock_response(status=200, body=short_html)
    monkeypatch.setattr(
        check_domains.urllib.request, "urlopen", lambda *a, **k: mock_resp
    )

    # Act
    result = check_domains.probe_domain("empty-shell.org", check_article=False)

    # Assert
    assert result.outcome == "UNREADABLE"
    assert "too short" in result.reason


def test_probe_domain_returns_not_html_when_content_type_is_pdf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    mock_resp = _make_mock_response(
        status=200,
        body="%PDF-1.4 ...",
        content_type="application/pdf",
    )
    monkeypatch.setattr(
        check_domains.urllib.request, "urlopen", lambda *a, **k: mock_resp
    )

    # Act
    result = check_domains.probe_domain("docs.org/report.pdf", check_article=False)

    # Assert
    assert result.outcome == "NOT_HTML"


def test_probe_domain_returns_timeout_on_read_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    def fake_urlopen(*args: Any, **kwargs: Any) -> Any:
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(check_domains.urllib.request, "urlopen", fake_urlopen)

    # Act
    result = check_domains.probe_domain("slow.com", check_article=False)

    # Assert
    assert result.outcome == "TIMEOUT"
    assert "timed out" in result.reason


def test_parse_args_defaults_and_custom_domains() -> None:
    # Arrange
    args_default = check_domains.parse_args([])
    args_custom = check_domains.parse_args(["bbc.com", "reuters.com", "--timeout", "5.0"])

    # Act
    targets_default = check_domains.resolve_targets(args_default)
    targets_custom = check_domains.resolve_targets(args_custom)

    # Assert
    assert set(check_domains.REMOVED_DOMAINS).issubset(set(targets_default))
    assert set(check_domains.ADDED_THINK_TANKS).issubset(set(targets_default))
    assert targets_custom == ["bbc.com", "reuters.com"]
    assert args_custom.timeout == 5.0


def test_resolve_targets_honors_flags() -> None:
    # Arrange
    args_removed = check_domains.parse_args(["--removed"])
    args_think_tanks = check_domains.parse_args(["--think-tanks"])
    args_all = check_domains.parse_args(["--all"])

    # Act
    targets_removed = check_domains.resolve_targets(args_removed)
    targets_think_tanks = check_domains.resolve_targets(args_think_tanks)
    targets_all = check_domains.resolve_targets(args_all)

    # Assert
    assert targets_removed == list(check_domains.REMOVED_DOMAINS)
    assert targets_think_tanks == list(check_domains.ADDED_THINK_TANKS)
    assert len(targets_all) > len(targets_removed)


def test_format_report_includes_summary_counts() -> None:
    # Arrange
    results = [
        check_domains.DomainCheckResult(
            target="ok.org",
            outcome="AVAILABLE",
            home_status=200,
            article_status=200,
            bytes_count=10240,
            title="OK Title",
            reason="OK",
        ),
        check_domains.DomainCheckResult(
            target="blocked.org",
            outcome="BLOCKED",
            home_status=403,
            article_status=None,
            bytes_count=500,
            title="",
            reason="Blocked",
        ),
    ]

    # Act
    report = check_domains.format_report(results)

    # Assert
    assert "ok.org" in report
    assert "blocked.org" in report
    assert "2 checked | 1 available | 1 blocked" in report


def test_main_prints_json_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    mock_resp = _make_mock_response(status=200, body=SAMPLE_HTML)
    monkeypatch.setattr(
        check_domains.urllib.request, "urlopen", lambda *a, **k: mock_resp
    )

    # Act
    exit_code = check_domains.main(["--json", "example.org"])
    captured = capsys.readouterr()

    # Assert
    assert exit_code == 0
    data = json.loads(captured.out)
    assert len(data) == 1
    assert data[0]["target"] == "example.org"
    assert data[0]["outcome"] == "AVAILABLE"


def test_main_prints_quiet_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Arrange
    mock_resp = _make_mock_response(status=200, body=SAMPLE_HTML)
    monkeypatch.setattr(
        check_domains.urllib.request, "urlopen", lambda *a, **k: mock_resp
    )

    # Act
    exit_code = check_domains.main(["--quiet", "example.org"])
    captured = capsys.readouterr()

    # Assert
    assert exit_code == 0
    assert captured.out.strip() == "example.org"
