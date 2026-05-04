# Referee Policy

This document defines the moderation policy used by the `referee` and `referee_blocked_summary` nodes.

## Purpose

The referee stage decides whether pipeline output can proceed to claim extraction and fact-checking, or must be blocked and summarized safely.

## Blocking Criteria

The referee should block when content includes one or more of the following:

- Direct incitement or endorsement of violence.
- Instructions that materially enable illegal harm.
- Dehumanizing political hate targeting protected classes.
- Coordinated disinformation framing presented as factual certainty without evidence.

The referee should **not** block solely due to viewpoint, ideology, or controversy if content remains non-violent and analyzable.

## Routing Contract

- `blocked = true` routes to `referee_blocked_summary`.
- `blocked = false` routes to `extract_claims`.

## Change Management

Any changes to referee behavior or thresholds should update this file in the same PR and be reviewed as policy changes, not just code changes.
