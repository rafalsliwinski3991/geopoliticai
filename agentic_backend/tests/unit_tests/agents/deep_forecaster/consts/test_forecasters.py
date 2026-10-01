"""Unit tests for `agents.deep_forecaster.consts.forecasters`."""

from agents.deep_forecaster.consts.forecasters import (
    FORECASTER_SOURCES,
    FORECASTERS,
    VIDEO_DOMAINS,
)


def test_the_ids_are_unique_and_lowercase() -> None:
    ids = [f.id for f in FORECASTERS]
    assert ids == [i.lower() for i in ids]
    assert len(ids) == len(set(ids))


def test_every_forecaster_has_at_least_one_domain() -> None:
    assert all(f.domains for f in FORECASTERS)


def test_the_policy_domains_are_the_union_with_no_duplicate() -> None:
    union = [d for f in FORECASTERS for d in f.domains]
    assert FORECASTER_SOURCES.allowed_domains == tuple(union)
    assert len(set(union)) == len(union)


def test_youtube_belongs_only_to_wojczal() -> None:
    assert all("youtube.com" not in f.domains for f in FORECASTERS if f.id != "wojczal")


def test_there_are_no_deferred_domains() -> None:
    assert FORECASTER_SOURCES.deferred_domains == frozenset()


def test_no_forecaster_is_named_masala() -> None:
    assert not any("Masala" in f.name for f in FORECASTERS)


def test_video_domains_is_the_video_set() -> None:
    assert VIDEO_DOMAINS == frozenset({"youtube.com"})
