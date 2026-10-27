"""Probe domains to verify HTTP availability, blocking status, and readability.

Used to test newsrooms, think tanks, and research sources from developer
machines or VPS hosts before editing or merging allow-lists.

Usage:
    python3 scripts/other/check_domains.py [domain_or_url ...]
    python3 scripts/other/check_domains.py --all
    python3 scripts/other/check_domains.py --removed
    python3 scripts/other/check_domains.py --sources
    python3 scripts/other/check_domains.py --think-tanks
    python3 scripts/other/check_domains.py --candidates
"""

from __future__ import annotations

import argparse
import concurrent.futures
import html as html_lib
import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Sequence

try:
    import trafilatura
except ImportError:  # pragma: no cover
    trafilatura = None

DEFAULT_TIMEOUT_SECONDS: float = 10.0
DEFAULT_WORKERS: int = 8
MIN_READABLE_TEXT_CHARS: int = 200
MAX_BODY_BYTES: int = 5 * 1024 * 1024

FETCH_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0.0.0"
        " Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

REMOVED_DOMAINS: tuple[str, ...] = (
    "reuters.com",
    "apnews.com",
    "france24.com",
    "ft.com",
    "economist.com",
    "axios.com",
    "politico.com",
    "nytimes.com",
    "wsj.com",
    "washingtonexaminer.com",
    "nationalreview.com",
    "washingtonpost.com",
)

ADDED_THINK_TANKS: tuple[str, ...] = (
    "carnegieendowment.org",
    "csis.org",
    "sipri.org",
    "ecfr.eu",
    "osw.waw.pl",
    "cfr.org",
    "atlanticcouncil.org",
    "cnas.org",
    "swp-berlin.org",
    "warontherocks.com",
)

CANDIDATE_DOMAINS: tuple[str, ...] = (
    "chathamhouse.org",
    "crisisgroup.org",
    "iiss.org",
    "pism.pl",
    "rand.org",
    "foreignaffairs.com",
)

ACTIVE_SOURCES: tuple[str, ...] = (
    "bbc.com",
    "npr.org",
    "aljazeera.com",
    "dw.com",
    "csmonitor.com",
    "bloomberg.com",
    "theguardian.com",
    "vox.com",
    "thenation.com",
    "motherjones.com",
    "thedispatch.com",
    "reason.com",
    "foxnews.com",
    "brookings.edu",
    "aei.org",
    "hoover.org",
    "carnegieendowment.org",
    "csis.org",
    "sipri.org",
    "ecfr.eu",
    "osw.waw.pl",
    "cfr.org",
    "atlanticcouncil.org",
    "cnas.org",
    "swp-berlin.org",
    "warontherocks.com",
)

STATIC_EXTENSIONS: frozenset[str] = frozenset({
    ".css",
    ".js",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".json",
    ".xml",
    ".rss",
    ".zip",
    ".gz",
})

BOT_CHALLENGE_PATTERNS: tuple[str, ...] = (
    "recaptcha/challengepage",
    "recaptchachallengepage",
    "cf-challenge",
    "just a moment...",
    "attention required! | cloudflare",
    "ddos protection by cloudflare",
    "please verify you are a human",
    "access to this page has been denied",
    "security check to access",
)

HTML_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
HTML_HREF_RE = re.compile(r"""href=["']([^"'#\s>]+)["']""", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
SCRIPT_STYLE_RE = re.compile(
    r"<(script|style|noscript)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE
)


@dataclass(frozen=True)
class HttpFetchResult:
    """The raw HTTP response and extracted metadata from one URL."""

    status_code: int
    final_url: str
    content_type: str
    body_bytes: int
    title: str
    text_chars: int
    html: str = ""
    error: str = ""


@dataclass(frozen=True)
class DomainCheckResult:
    """The combined availability verdict for one domain or target URL."""

    target: str
    outcome: str
    home_status: int
    article_status: int | None
    bytes_count: int
    title: str
    reason: str


def clean_html_text(html: str) -> str:
    """Strip script/style tags, HTML tags, and collapse whitespace."""
    stripped = SCRIPT_STYLE_RE.sub(" ", html)
    no_tags = HTML_TAG_RE.sub(" ", stripped)
    return WHITESPACE_RE.sub(" ", no_tags).strip()


def extract_title(html: str) -> str:
    """Extract and unescape the <title> tag text from an HTML document."""
    match = HTML_TITLE_RE.search(html)
    if not match:
        return ""
    raw = WHITESPACE_RE.sub(" ", match.group(1)).strip()
    return html_lib.unescape(raw)


def extract_text(html: str) -> str:
    """Extract readable text using trafilatura if available, else plain HTML strip."""
    if trafilatura is not None:
        extracted = trafilatura.extract(html)
        if extracted:
            return extracted
    return clean_html_text(html)


def find_article_links(html: str, base_url: str, domain: str) -> list[str]:
    """Find candidate article or subpage URLs within the same domain."""
    candidates: list[str] = []
    seen: set[str] = set()
    base_netloc = urllib.parse.urlparse(base_url).netloc.lower()

    for match in HTML_HREF_RE.finditer(html):
        href = match.group(1).strip()
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        full_url = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlparse(full_url)
        if parsed.scheme not in ("http", "https"):
            continue
        netloc = parsed.netloc.lower()
        if (
            netloc != base_netloc
            and not netloc.endswith(f".{domain}")
            and netloc != domain
        ):
            continue
        path = parsed.path.lower()
        if any(path.endswith(ext) for ext in STATIC_EXTENSIONS):
            continue
        if path in ("", "/"):
            continue
        if full_url in seen:
            continue
        seen.add(full_url)
        candidates.append(full_url)

    priority_keywords = (
        "/article",
        "/story",
        "/news",
        "/research",
        "/report",
        "/202",
        "/analysis",
        "/press-release",
        "/publication",
    )
    high_priority = [
        c for c in candidates if any(k in c.lower() for k in priority_keywords)
    ]
    return high_priority or candidates


def fetch_url(url: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> HttpFetchResult:
    """Fetch one URL with the standard fetch headers and extract its metadata."""
    req = urllib.request.Request(url, headers=FETCH_HEADERS)
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            status_code = resp.status
            final_url = resp.geturl()
            content_type = resp.headers.get("content-type", "").lower()
            body = resp.read(MAX_BODY_BYTES)
            text_preview = body.decode("utf-8", errors="ignore")
            title = extract_title(text_preview)
            text_chars = len(extract_text(text_preview))
            return HttpFetchResult(
                status_code=status_code,
                final_url=final_url,
                content_type=content_type,
                body_bytes=len(body),
                title=title,
                text_chars=text_chars,
                html=text_preview,
            )
    except urllib.error.HTTPError as exc:
        body = exc.read(65536)
        text_preview = body.decode("utf-8", errors="ignore")
        title = extract_title(text_preview)
        content_type = (
            exc.headers.get("content-type", "").lower() if exc.headers else ""
        )
        return HttpFetchResult(
            status_code=exc.code,
            final_url=exc.geturl() if hasattr(exc, "geturl") else url,
            content_type=content_type,
            body_bytes=len(body),
            title=title,
            text_chars=0,
            html=text_preview,
            error=f"HTTP Error {exc.code}: {exc.reason}",
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = str(exc)
        if isinstance(exc, urllib.error.URLError) and exc.reason:
            reason = str(exc.reason)
        return HttpFetchResult(
            status_code=0,
            final_url=url,
            content_type="",
            body_bytes=0,
            title="",
            text_chars=0,
            error=reason,
        )


def probe_domain(
    domain_or_url: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    check_article: bool = True,
) -> DomainCheckResult:
    """Probe a domain or URL for availability, blocking, and readability."""
    target = domain_or_url.strip()
    if not target:
        return DomainCheckResult(
            target="",
            outcome="FAILED",
            home_status=0,
            article_status=None,
            bytes_count=0,
            title="",
            reason="Empty target domain or URL",
        )

    if "://" in target:
        base_url = target
        domain = urllib.parse.urlparse(target).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
    else:
        domain = target.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        base_url = f"https://{target}"

    home_result = fetch_url(base_url, timeout=timeout)

    if home_result.status_code in (401, 403, 429):
        return DomainCheckResult(
            target=target,
            outcome="BLOCKED",
            home_status=home_result.status_code,
            article_status=None,
            bytes_count=home_result.body_bytes,
            title=home_result.title,
            reason=f"Homepage blocked: {home_result.error}",
        )

    if home_result.status_code == 0:
        outcome = "TIMEOUT" if "timed out" in home_result.error.lower() else "FAILED"
        return DomainCheckResult(
            target=target,
            outcome=outcome,
            home_status=0,
            article_status=None,
            bytes_count=0,
            title="",
            reason=f"Homepage fetch failed: {home_result.error}",
        )

    if home_result.status_code >= 400:
        return DomainCheckResult(
            target=target,
            outcome="FAILED",
            home_status=home_result.status_code,
            article_status=None,
            bytes_count=home_result.body_bytes,
            title=home_result.title,
            reason=f"Homepage HTTP error: {home_result.error}",
        )

    home_body_lower = home_result.html.lower()
    home_title_lower = home_result.title.lower()
    if any(p in home_body_lower or p in home_title_lower for p in BOT_CHALLENGE_PATTERNS):
        return DomainCheckResult(
            target=target,
            outcome="BLOCKED",
            home_status=home_result.status_code,
            article_status=None,
            bytes_count=home_result.body_bytes,
            title=home_result.title,
            reason="Bot challenge or captcha detected",
        )

    if "html" not in home_result.content_type:
        return DomainCheckResult(
            target=target,
            outcome="NOT_HTML",
            home_status=home_result.status_code,
            article_status=None,
            bytes_count=home_result.body_bytes,
            title=home_result.title,
            reason=f"Non-HTML content: {home_result.content_type}",
        )

    if home_result.text_chars < MIN_READABLE_TEXT_CHARS:
        return DomainCheckResult(
            target=target,
            outcome="UNREADABLE",
            home_status=home_result.status_code,
            article_status=None,
            bytes_count=home_result.body_bytes,
            title=home_result.title,
            reason=(
                f"Homepage text too short ({home_result.text_chars} chars,"
                f" minimum {MIN_READABLE_TEXT_CHARS})"
            ),
        )

    article_status: int | None = None
    if check_article and "://" not in domain_or_url:
        links = find_article_links(home_result.html, home_result.final_url, domain)
        if links:
            article_result = fetch_url(links[0], timeout=timeout)
            article_status = article_result.status_code
            if article_result.status_code in (401, 403, 429):
                return DomainCheckResult(
                    target=target,
                    outcome="BLOCKED",
                    home_status=home_result.status_code,
                    article_status=article_status,
                    bytes_count=home_result.body_bytes,
                    title=home_result.title,
                    reason=f"Article blocked: HTTP {article_result.status_code} ({links[0]})",
                )
            article_body_lower = article_result.html.lower()
            article_title_lower = article_result.title.lower()
            if any(
                p in article_body_lower or p in article_title_lower
                for p in BOT_CHALLENGE_PATTERNS
            ):
                return DomainCheckResult(
                    target=target,
                    outcome="BLOCKED",
                    home_status=home_result.status_code,
                    article_status=article_status,
                    bytes_count=home_result.body_bytes,
                    title=home_result.title,
                    reason=f"Article bot challenge or captcha detected ({links[0]})",
                )

    return DomainCheckResult(
        target=target,
        outcome="AVAILABLE",
        home_status=home_result.status_code,
        article_status=article_status,
        bytes_count=home_result.body_bytes,
        title=home_result.title,
        reason="OK",
    )


def run_checks(
    targets: Sequence[str],
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    workers: int = DEFAULT_WORKERS,
    check_article: bool = True,
) -> list[DomainCheckResult]:
    """Probe multiple domains concurrently while preserving input order."""
    if not targets:
        return []
    max_workers = max(1, min(workers, len(targets)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_target = {
            executor.submit(probe_domain, target, timeout, check_article): target
            for target in targets
        }
        results = [
            future.result()
            for future in concurrent.futures.as_completed(future_to_target)
        ]
    target_order = {t: i for i, t in enumerate(targets)}
    results.sort(key=lambda r: target_order.get(r.target, 0))
    return results


def format_report(results: Sequence[DomainCheckResult]) -> str:
    """Format check results into a human-readable table."""
    lines: list[str] = [
        f"{'Target':<26} {'Status':<12} {'HTTP':<6} {'Article':<8} {'Bytes':<10} {'Details'}",
        "-" * 100,
    ]
    for r in results:
        art = str(r.article_status) if r.article_status is not None else "-"
        http = str(r.home_status) if r.home_status else "-"
        kb = f"{r.bytes_count / 1024:.1f} KB" if r.bytes_count else "-"
        detail = r.title if r.outcome == "AVAILABLE" and r.title else r.reason
        lines.append(
            f"{r.target:<26} {r.outcome:<12} {http:<6} {art:<8} {kb:<10} {detail}"
        )

    available = sum(1 for r in results if r.outcome == "AVAILABLE")
    blocked = sum(1 for r in results if r.outcome == "BLOCKED")
    failed = len(results) - available - blocked

    lines.extend([
        "-" * 100,
        (
            f"Summary: {len(results)} checked | {available} available |"
            f" {blocked} blocked | {failed} timeout/failed/other"
        ),
    ])
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Probe domains to verify HTTP availability, blocking status, and readability."
    )
    parser.add_argument(
        "domains",
        nargs="*",
        help="Domains or URLs to check (e.g. reuters.com, sipri.org)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Check all domains (active sources, removed outlets, and candidates)",
    )
    parser.add_argument(
        "--removed",
        action="store_true",
        help="Check the 12 removed news outlets (Reuters, AP, FT, etc.)",
    )
    parser.add_argument(
        "--sources",
        action="store_true",
        help="Check active sources from sources.py",
    )
    parser.add_argument(
        "--think-tanks",
        action="store_true",
        help="Check the 10 added think tanks (Carnegie, CSIS, SIPRI, etc.)",
    )
    parser.add_argument(
        "--candidates",
        action="store_true",
        help="Check evaluated candidates (Chatham House, Crisis Group, IISS, etc.)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"Per-request timeout in seconds (default: {DEFAULT_TIMEOUT_SECONDS})",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Concurrent worker threads (default: {DEFAULT_WORKERS})",
    )
    parser.add_argument(
        "--no-articles",
        action="store_true",
        help="Skip probing article links from homepages",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Print only available domains (one per line)",
    )
    return parser.parse_args(argv)


def resolve_targets(args: argparse.Namespace) -> list[str]:
    """Determine the list of domains to probe based on command-line flags."""
    if args.domains:
        return list(dict.fromkeys(args.domains))

    targets: list[str] = []
    if args.all:
        targets.extend(REMOVED_DOMAINS)
        targets.extend(ADDED_THINK_TANKS)
        targets.extend(CANDIDATE_DOMAINS)
        targets.extend(ACTIVE_SOURCES)
    else:
        if args.removed:
            targets.extend(REMOVED_DOMAINS)
        if args.think_tanks:
            targets.extend(ADDED_THINK_TANKS)
        if args.candidates:
            targets.extend(CANDIDATE_DOMAINS)
        if args.sources:
            targets.extend(ACTIVE_SOURCES)

    if not targets:
        targets.extend(REMOVED_DOMAINS)
        targets.extend(ADDED_THINK_TANKS)

    return list(dict.fromkeys(targets))


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line domain availability checker."""
    args = parse_args(argv)
    targets = resolve_targets(args)
    if not targets:
        print("No domains specified to check.", file=sys.stderr)
        return 1

    results = run_checks(
        targets=targets,
        timeout=args.timeout,
        workers=args.workers,
        check_article=not args.no_articles,
    )

    if args.json:
        payload = [asdict(r) for r in results]
        print(json.dumps(payload, indent=2))
    elif args.quiet:
        for r in results:
            if r.outcome == "AVAILABLE":
                print(r.target)
    else:
        print(format_report(results))

    return 0


if __name__ == "__main__":
    sys.exit(main())
