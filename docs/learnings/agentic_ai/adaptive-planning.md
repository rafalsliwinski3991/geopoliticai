# Essential Learnings

## 1. A model should decide, not directly execute

The model may propose a `ToolCall`, but application code must authorize and
execute it. A model-generated object is not a permission.

## 2. MCP is a connector, not a safety system

MCP can connect a model to tools and data. It does not automatically provide
authorization, prompt-injection protection, human approval, or audit logging.

## 3. Capabilities should be allow-listed

Explicitly listing allowed tools is stronger than asking the model not to use
dangerous tools in a prompt. Missing capabilities cannot be requested through
the typed registry.

## 4. Policy should have one owner

Centralizing limits and permissions in `BriefingPolicy` makes behavior easier to
test and prevents different parts of the application from applying different
rules.

## 5. External content is data, not instructions

An email can contain an instruction-like sentence without gaining authority
over the agent. Untrusted text should be detected, marked, and constrained.

## 6. Normalize before model use

Never treat a complete raw API response as model context by default. Normalize
it into a bounded, typed representation first.

## 7. Keep evidence attached to conclusions

Evidence IDs make priorities and drafts traceable. A useful assistant should be
able to answer, "Where did this conclusion come from?"

## 8. Ground important arguments

A thread ID must come from a previous trusted result. Correct syntax is not the
same as valid provenance.

## 9. Separate preparation from side effects

Preparing a draft and sending a message are different operations. The project
stops at preparation and requires a human gate before any world-changing step.

## 10. Human approval is application state

Approval, rejection, editing, waiting, and no-data states should be explicit
values in the system, not hidden behavior inside a prompt or button callback.

## 11. Audit decisions, not only errors

Successful normalization, blocked calls, flagged content, and human choices are
all important events. An audit trail supports debugging, security review, and
user trust.

## 12. Use stable adapter interfaces

The fake and real clients expose the same operations. This allows deterministic
testing without rewriting the application when the data source changes.

## 13. Let deterministic code own guarantees

Use the model for flexible judgment and language. Use ordinary code for
permissions, limits, validation, normalization, side effects, state transitions,
and audit records.

## 14. Empty results are valid

An honest system can return no priorities and no drafts. It should not invent
work just to produce an impressive-looking answer.

## 15. Failure must remain visible

Missing binaries, timeouts, invalid JSON, forbidden tools, suspicious content,
and rejected actions should remain distinguishable from successful execution.

## 16. Test contracts and adversarial paths

The self-test and notebook exercises check more than the happy path. They test
injection markers, invented IDs, excessive limits, empty data, forbidden tools,
and tool failures.

## The Seven-Layer Pattern To Remember

```text
1. Registry      What capabilities exist?
2. Decision      What does the model want to do?
3. Policy        Is it allowed?
4. Router        Which adapter executes it?
5. Normalizer    What data is safe and useful?
6. Human Gate    Does a person need to decide?
7. Audit         What happened and why?
```

This pattern is reusable for assistants that work with email, calendars,
databases, CRMs, ticketing systems, or other external tools.

## Final Summary

The learnings are about how to build an agent that can use external tools while
keeping permissions, untrusted data, context, side effects, human approval,
and auditability under deterministic application control.
