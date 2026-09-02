"""Recompute a case's corpus lock from its local excerpt files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.corpus import CASES_ROOT, CORPUS_LOCK_NAME, Excerpt, corpus_digest


def _read_excerpt(path: Path) -> Excerpt:
    """Read one local corpus excerpt without fetching or altering its text."""
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return Excerpt(
        excerpt_id=str(payload["excerpt_id"]),
        title=str(payload["title"]),
        url=str(payload["url"]),
        domain=str(payload["domain"]),
        publisher=str(payload["publisher"]),
        published_at=str(payload["published_at"]),
        retrieved_at=str(payload["retrieved_at"]),
        truncation_note=str(payload["truncation_note"]),
        text=str(payload["text"]),
    )


def freeze_case(case_id: str, *, root: Path = CASES_ROOT) -> None:
    """Recompute and write the SHA-256 lock for one local case."""
    case_dir = root / case_id
    excerpts = tuple(
        _read_excerpt(path) for path in sorted((case_dir / "corpus").glob("*.json"))
    )
    lock_payload: dict[str, Any] = {
        "excerpts": {excerpt.excerpt_id: excerpt.digest() for excerpt in excerpts},
        "corpus_digest": corpus_digest(excerpts),
    }
    (case_dir / CORPUS_LOCK_NAME).write_text(
        json.dumps(lock_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    freeze_case("finland_nato")
