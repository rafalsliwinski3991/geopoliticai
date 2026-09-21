from agents.expert.consts.sources import (
    ALLOWED_DOMAINS,
    EXPERT_SOURCES,
    HARD_PAYWALLED_DOMAINS,
    SEARCH_BATCHES,
)


def test_batches_partition_allowlist() -> None:
    # Arrange
    batched = [domain for batch in SEARCH_BATCHES for domain in batch]
    # Assert
    assert sorted(batched) == sorted(ALLOWED_DOMAINS)
    assert len(batched) == len(set(batched))


def test_paywalled_domains_are_allowed() -> None:
    # Assert
    assert HARD_PAYWALLED_DOMAINS <= set(ALLOWED_DOMAINS)


def test_domains_are_bare_hosts() -> None:
    # Assert
    assert all(
        "://" not in domain and "/" not in domain and not domain.startswith("www.")
        for domain in ALLOWED_DOMAINS
    )


def test_policy_matches_constants() -> None:
    # Assert
    assert EXPERT_SOURCES.allowed_domains == ALLOWED_DOMAINS
    assert EXPERT_SOURCES.batches == SEARCH_BATCHES
    assert EXPERT_SOURCES.deferred_domains == HARD_PAYWALLED_DOMAINS
