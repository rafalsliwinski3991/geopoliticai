"""Frozen evidence: bounded excerpts that Git owns and Phoenix only mirrors.

Each excerpt is a JSON file carrying provenance (title, publisher, URL,
publication and retrieval dates, a truncation note) and the excerpt text.
`corpus.lock.json` records a SHA-256 per excerpt plus a corpus-level digest;
every load verifies them, and a mismatch is an `InvalidRunError`, never a
score. That is what makes "reproducible from Git-owned definitions" checkable
rather than aspirational.

Excerpts are bounded on purpose (brainstorm: "Evaluation ownership and
frozen-source storage"): this repository does not redistribute complete
commercial articles, and the benchmark therefore does not test full-article
selection.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.errors import InvalidRunError
from models import Source

CASES_ROOT = Path(__file__).resolve().parent / "cases"
CORPUS_LOCK_NAME = "corpus.lock.json"
CASE_NAME = "case.json"


@dataclass(frozen=True)
class Excerpt:
    """One bounded, provenance-carrying source excerpt."""

    excerpt_id: str
    title: str
    url: str
    domain: str
    publisher: str
    published_at: str
    retrieved_at: str
    truncation_note: str
    text: str

    def as_source(self) -> Source:
        """Return this excerpt as the `Source` the fetch boundary would return."""
        return Source(title=self.title, url=self.url, text=self.text)

    def digest(self) -> str:
        """Return the SHA-256 of the excerpt text, as stored in the lock file."""
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Case:
    """One benchmark case: a question, an expected route, and frozen evidence."""

    case_id: str
    question: str
    expected_destination: str
    rubric_version: str
    corpus_digest: str
    excerpts: tuple[Excerpt, ...]

    @property
    def sources(self) -> list[Source]:
        """Return every excerpt as a `Source`, in corpus order."""
        return [excerpt.as_source() for excerpt in self.excerpts]


def _read_json(path: Path) -> dict[str, Any]:
    """Read one JSON object, or fail the run."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InvalidRunError(f"Unreadable evaluation definition: {path}") from exc
    if not isinstance(payload, dict):
        raise InvalidRunError(f"Evaluation definition is not an object: {path}")
    return payload


def corpus_digest(excerpts: tuple[Excerpt, ...]) -> str:
    """Return the corpus-level digest: SHA-256 over sorted per-excerpt digests."""
    joined = "\n".join(
        f"{excerpt.excerpt_id}:{excerpt.digest()}"
        for excerpt in sorted(excerpts, key=lambda item: item.excerpt_id)
    )
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def load_case(case_id: str, *, root: Path | None = None) -> Case:
    """Load and hash-verify one case. Any inconsistency invalidates the run."""
    case_dir = (root or CASES_ROOT) / case_id
    case_payload = _read_json(case_dir / CASE_NAME)
    lock_payload = _read_json(case_dir / CORPUS_LOCK_NAME)
    locked: dict[str, str] = dict(lock_payload.get("excerpts", {}))

    excerpts: list[Excerpt] = []
    for path in sorted((case_dir / "corpus").glob("*.json")):
        raw = _read_json(path)
        excerpt = Excerpt(
            excerpt_id=str(raw["excerpt_id"]),
            title=str(raw["title"]),
            url=str(raw["url"]),
            domain=str(raw["domain"]),
            publisher=str(raw["publisher"]),
            published_at=str(raw["published_at"]),
            retrieved_at=str(raw["retrieved_at"]),
            truncation_note=str(raw["truncation_note"]),
            text=str(raw["text"]),
        )
        expected = locked.get(excerpt.excerpt_id)
        if expected is None:
            raise InvalidRunError(
                f"Excerpt not in {CORPUS_LOCK_NAME}: {excerpt.excerpt_id}"
            )
        if expected != excerpt.digest():
            raise InvalidRunError(
                f"Excerpt text changed since it was frozen: {excerpt.excerpt_id}"
            )
        excerpts.append(excerpt)

    if len(excerpts) != len(locked):
        raise InvalidRunError(
            f"{CORPUS_LOCK_NAME} lists {len(locked)} excerpts; {len(excerpts)} files found."
        )
    frozen = tuple(excerpts)
    digest = corpus_digest(frozen)
    if digest != str(lock_payload.get("corpus_digest", "")):
        raise InvalidRunError("Corpus digest does not match the lock file.")

    return Case(
        case_id=case_id,
        question=str(case_payload["question"]),
        expected_destination=str(case_payload["expected_destination"]),
        rubric_version=str(case_payload["rubric_version"]),
        corpus_digest=digest,
        excerpts=frozen,
    )


def combined_context(case: Case) -> str:
    """Render the whole corpus as the judge's and grounder's single context.

    Deliberately the *entire* bounded corpus, not the sources the agent chose:
    the settled design gives the judge the full frozen corpus and lets it decide
    what mattered, and `faithful_to_combined_context` is named after exactly
    this string.
    """
    return "\n\n".join(
        f"--- SOURCE ---\nTitle: {excerpt.title}\nURL: {excerpt.url}\n\n{excerpt.text}"
        for excerpt in case.excerpts
    )
