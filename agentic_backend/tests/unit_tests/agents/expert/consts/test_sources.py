from agents.expert.consts.sources import (
    ALLOWED_DOMAINS,
    EXPERT_SOURCES,
    HARD_PAYWALLED_DOMAINS,
    SEARCH_BATCHES,
)
from services.web_search import build_batch_query

BRAVE_MAX_DOMAINS_PER_BATCH = 10
LONGEST_QUESTION = " ".join(["international"] * 9 + ["geopolitically"])
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
    batches = SEARCH_BATCHES
    # Act
    sizes = [len(batch) for batch in batches]
    # Assert
    assert max(sizes) <= BRAVE_MAX_DOMAINS_PER_BATCH


def test_the_longest_question_is_the_length_the_batch_check_assumes() -> None:
    """The query-limit test is only as hard as its question is long; a shorter one would pass for the wrong reason."""
    # Arrange
    expected_length = 140

    # Act
    length = len(LONGEST_QUESTION)

    # Assert
    assert length == expected_length


def test_no_batch_loses_a_domain_to_the_query_limit() -> None:
    """A long question plus a long batch can pass Brave's 400 characters, and the builder then drops domains."""
    # Arrange
    question = LONGEST_QUESTION
    # Act
    queries = [build_batch_query(question, batch) for batch in SEARCH_BATCHES]
    # Assert
    for batch, query in zip(SEARCH_BATCHES, queries, strict=True):
        assert all(f"site:{domain}" in query for domain in batch)


def test_the_think_tanks_are_on_the_list() -> None:
    """The expert reads institutes as well as newsrooms; losing one removes a whole kind of source."""
    # Arrange
    expected = set(THINK_TANKS)
    # Act
    missing = expected - set(ALLOWED_DOMAINS)
    # Assert
    assert missing == set()
