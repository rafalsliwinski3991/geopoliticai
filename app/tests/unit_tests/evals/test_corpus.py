import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from evals.corpus import CORPUS_LOCK_NAME, Case, combined_context, load_case
from evals.errors import InvalidRunError
from models import Source

FIXTURE_CASE = Path(__file__).parent / "fixtures" / "synthetic_case"
CASE_ID = "synthetic_case"
EXPECTED_CORPUS_DIGEST = (
    "2ae408e49d906ae2372cbe3652fc7505d1c19a95c46506024a97e9f59003fbef"
)


def _copy_synthetic_case(tmp_path: Path) -> Path:
    root = tmp_path / "cases"
    case_dir = root / CASE_ID
    shutil.copytree(FIXTURE_CASE, case_dir)

    excerpt_digests: dict[str, str] = {}
    for path in sorted((case_dir / "corpus").glob("*.json")):
        payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        excerpt_id = str(payload["excerpt_id"])
        text = str(payload["text"])
        excerpt_digests[excerpt_id] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    joined = "\n".join(
        f"{excerpt_id}:{excerpt_digests[excerpt_id]}"
        for excerpt_id in sorted(excerpt_digests)
    )
    lock_payload = {
        "excerpts": excerpt_digests,
        "corpus_digest": hashlib.sha256(joined.encode("utf-8")).hexdigest(),
    }
    (case_dir / CORPUS_LOCK_NAME).write_text(
        json.dumps(lock_payload, indent=2), encoding="utf-8"
    )
    return root


def test_clean_synthetic_case_loads(tmp_path: Path) -> None:
    root = _copy_synthetic_case(tmp_path)

    case = load_case(CASE_ID, root=root)

    assert len(case.excerpts) == 2
    assert case.corpus_digest == EXPECTED_CORPUS_DIGEST


def test_mutated_excerpt_text_invalidates_run(tmp_path: Path) -> None:
    root = _copy_synthetic_case(tmp_path)
    excerpt_path = root / CASE_ID / "corpus" / "01_alpha.json"
    payload: dict[str, Any] = json.loads(excerpt_path.read_text(encoding="utf-8"))
    payload["text"] = "Mutated synthetic evidence."
    excerpt_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with pytest.raises(InvalidRunError):
        load_case(CASE_ID, root=root)


def test_missing_excerpt_file_invalidates_run(tmp_path: Path) -> None:
    root = _copy_synthetic_case(tmp_path)
    (root / CASE_ID / "corpus" / "01_alpha.json").unlink()

    with pytest.raises(InvalidRunError):
        load_case(CASE_ID, root=root)


def test_unlocked_excerpt_invalidates_run(tmp_path: Path) -> None:
    root = _copy_synthetic_case(tmp_path)
    excerpt_path = root / CASE_ID / "corpus" / "03_gamma.json"
    payload: dict[str, Any] = json.loads(
        (root / CASE_ID / "corpus" / "02_beta.json").read_text(encoding="utf-8")
    )
    payload["excerpt_id"] = "03_synthetic_gamma"
    excerpt_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    with pytest.raises(InvalidRunError):
        load_case(CASE_ID, root=root)


def test_stale_corpus_digest_invalidates_run(tmp_path: Path) -> None:
    root = _copy_synthetic_case(tmp_path)
    lock_path = root / CASE_ID / CORPUS_LOCK_NAME
    lock_payload: dict[str, Any] = json.loads(lock_path.read_text(encoding="utf-8"))
    lock_payload["corpus_digest"] = "0" * 64
    lock_path.write_text(json.dumps(lock_payload, indent=2), encoding="utf-8")

    with pytest.raises(InvalidRunError):
        load_case(CASE_ID, root=root)


def test_combined_context_contains_every_url_once(tmp_path: Path) -> None:
    root = _copy_synthetic_case(tmp_path)
    case = load_case(CASE_ID, root=root)

    context = combined_context(case)

    for excerpt in case.excerpts:
        assert context.count(excerpt.url) == 1


def test_as_source_produces_models_source(tmp_path: Path) -> None:
    root = _copy_synthetic_case(tmp_path)
    case: Case = load_case(CASE_ID, root=root)

    source = case.excerpts[0].as_source()

    assert isinstance(source, Source)
    assert source.title == case.excerpts[0].title
    assert source.url == case.excerpts[0].url
    assert source.text == case.excerpts[0].text
