from agents.expert.consts.sources import (
    ALLOWED_DOMAINS,
    EXPERT_SOURCES,
    HARD_PAYWALLED_DOMAINS,
    SEARCH_BATCHES,
)
from search import build_batch_query

BRAVE_MAX_DOMAINS_PER_BATCH = 10
LONGEST_QUESTION = " ".join(["geopolitics"] * 11)[:140].rstrip()
THINK_TANKS = (
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


def test_no_batch_holds_more_than_ten_domains() -> None:
    """Brave reads at most ten site: filters in one query, so a bigger batch silently loses domains."""
    # Arrange
    sizes = [len(batch) for batch in SEARCH_BATCHES]
    # Assert
    assert max(sizes) <= BRAVE_MAX_DOMAINS_PER_BATCH


def test_no_batch_loses_a_domain_to_the_query_limit() -> None:
    """A long question plus a long batch can pass Brave's 400 characters, and the builder then drops domains."""
    # Arrange
    assert len(LONGEST_QUESTION) > 130
    # Act
    queries = [build_batch_query(LONGEST_QUESTION, batch) for batch in SEARCH_BATCHES]
    # Assert
    for batch, query in zip(SEARCH_BATCHES, queries, strict=True):
        assert all(f"site:{domain}" in query for domain in batch)


def test_the_think_tanks_are_on_the_list() -> None:
    """The expert reads institutes as well as newsrooms; losing one removes a whole kind of source."""
    # Assert
    assert set(THINK_TANKS) <= set(ALLOWED_DOMAINS)
