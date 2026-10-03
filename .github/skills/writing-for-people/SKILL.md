---
name: writing-for-people
description: "INVOKE THIS SKILL before writing prose a person reads to make a decision: a pull-request description, a guidebook page, or a run report."
---

# Writing for people

The reader is deciding something, usually whether to merge. Write so they can act after one read. These
rules condense [humanizer](https://github.com/blader/humanizer) v3.1.0 by Siqi Chen (MIT; see
`HUMANIZER-LICENSE`), which draws on Wikipedia's "Signs of AI writing".

## Three rules that come first

1. Lead with the decision or the effect. Give background after it, and only the part that changes what the
   reader does.
2. Every sentence adds a fact the reader does not have yet. Cut a sentence that only restates.
3. Keep every fact. Never add a name, number, path, SHA, status, or claim the sources do not hold, and never
   drop one to make a sentence shorter.

## Patterns to remove on one sighting

1. **Not X but Y.** "This is not just a cap, it is a guarantee." Write the point: "The cap stops the run at
   480 s." Keep a contrast only when it corrects something the reader believes.
2. **One-line closers** after a paragraph ("Simple. Safe. Done."). Delete them.
3. **A run-up before the point** ("Here's the thing:", "The key insight is"). Start with the point.
4. **Forced threes.** A list of three where the meaning has one or two. Keep three only when there are three.
5. **Dashes as the connector for everything.** Use a period, comma, colon, or parentheses. Dashes inside code,
   paths, commands, and URLs stay.
6. **Bold as decoration**, and lists where every item has a bold label and a colon. Bold at most one thing per
   section, and only what the reader must not miss.
7. **Inflated words:** crucial, robust, seamless, pivotal, comprehensive, leverage, delve, testament. Say what
   the thing does.
8. **Stacked qualifiers** ("may potentially", "generally tends to"). Keep one or none.
9. **Chat leftovers:** "Great question", "I hope this helps", "Let me know if", "In summary", "Overall".
10. **Writing about the document** ("This section explains…"). Say the thing itself.
11. **A missing actor.** "The key is checked" becomes "`startup()` checks the key".

Leave a pattern alone inside a quotation, a title, a proper name, or code.

## Shape

- Short sentences, one idea each. Vary the length a little.
- Use a table when items share columns, a numbered list when order matters, and prose otherwise.
- Put exact identifiers in `code`: paths, PR numbers, SHAs, commands.
- Headings name content ("How to review it"). They never decorate it.
- When a section has nothing to report, say so in one line ("Audit clean.") rather than padding it.

## Check before you finish

Read the draft once more. Ask what still sounds generated, and whether the rewrite added or lost a fact.
Then search again for patterns 1, 2, 4, 5, and 6, which survive edits most often.
