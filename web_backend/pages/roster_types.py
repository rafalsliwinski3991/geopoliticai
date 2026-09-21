"""Types for the landing roster in `pages.consts` (unit 11)."""

from __future__ import annotations

from typing import NamedTuple


class Band(NamedTuple):
    """One band of the public source spectrum."""

    label: str
    slot: str
    domains: tuple[str, ...]
    institutes: frozenset[str]


class _Roster(NamedTuple):
    """The full roster and its convenience counts."""

    bands: tuple[Band, ...]

    def domains(self) -> tuple[str, ...]:
        return tuple(domain for band in self.bands for domain in band.domains)

    @property
    def total(self) -> int:
        return len(self.domains())
