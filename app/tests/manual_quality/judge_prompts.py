"""The four rubric prompts used by the manual quality judges."""

GROUNDEDNESS_PROMPT = """
Judge how well the answer is grounded in the supplied fetched source text.
Treat the source list as the only evidence. Check that material factual claims
are supported and that each inline URL is the URL of the source supporting it.

Question:
{question}

Answer:
{answer}

Sources:
{sources}

Choose exactly one label:
1: material claims are unsupported/contradicted or citations are mostly missing/wrong.
2: some core support exists, but substantial unsupported content or citation errors remain.
3: the main answer is supported, with one meaningful sourcing or citation weakness.
4: all material claims are supported and linked correctly, with only a minor issue.
5: every factual claim is supported by supplied source text and carries the exact supporting inline URL.

Give a concise evidence-based explanation for the label. Refer only to
observable claims, citations, and source text; do not provide private
chain-of-thought.
"""

USEFULNESS_PROMPT = """
Judge whether the answer directly and clearly resolves the question, using the
listed requirements as a coverage checklist rather than as factual evidence.

Question:
{question}

Answer:
{answer}

Required points:
{requirements}

Choose exactly one label:
1: does not answer the central question or is unusable.
2: answers only one part or contains major irrelevant/confusing material.
3: answers both parts basically but lacks an important causal connection or clear prioritization.
4: covers every required point with a minor omission or a small loss of precision.
5: covers every required point precisely, with the causal connections between them made explicit and no material omission.

Give a concise evidence-based explanation for the label. Identify covered or
missing requirements; do not provide private chain-of-thought.
"""

REWRITE_QUALITY_PROMPT = """
Judge whether the standalone rewrite faithfully resolves the last user turn
from the conversation history. The expected intent is a semantic target, not
text that must be copied.

Conversation history:
{history}

Standalone rewrite:
{rewrite}

Expected intent:
{expected_intent}

Choose exactly one label:
1: does not resolve the referent of the last user turn, or changes the user's meaning.
2: names the referent but stays materially ambiguous, or asks a different question.
3: is self-contained but loosely preserves the intent, or imports an assumption the history does not support.
4: matches the expected intent with a small loss of nuance.
5: fully matches the expected intent, self-contained, importing nothing the history does not support.

Give a concise evidence-based explanation for the label. Point to the rewrite's
observable wording; do not provide private chain-of-thought.
"""

REPORT_FIDELITY_PROMPT = """
Judge whether the report covers the intended outline and stays within the
research supplied in the conversation. Treat the conversation as the only
evidence available to the report's author.

Conversation:
{conversation}

Intended coverage:
{outline_intent}

Report:
{report}

Choose exactly one label:
1: ignores the intended coverage, or asserts material facts the conversation never established.
2: covers a minority of the intended coverage, or contains substantial unsupported material.
3: covers most of the intended coverage with one meaningful gap or one unsupported claim.
4: covers all of the intended coverage with a minor gap or a small unsupported detail.
5: covers all of the intended coverage, in a coherent order, asserting nothing the conversation did not establish.

Give a concise evidence-based explanation for the label. Refer only to
observable content; do not provide private chain-of-thought.
"""
