"""Text helpers shared by every layer."""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator


def squash_whitespace(text: str) -> str:
    """Return `text` with each run of whitespace made one space and the ends trimmed."""
    return " ".join(text.split())


# A schema field of this type arrives with its whitespace squashed. Defined after
# the function it applies, the way `shared.config.DEFAULT_LLM_SETTINGS` follows its class.
CleanText = Annotated[str, AfterValidator(squash_whitespace)]
