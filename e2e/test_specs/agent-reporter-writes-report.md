# The report agent outlines and writes a report

## Preconditions
- Logged in as the E2E test user, with at least 2 research units left.

## Steps
1. Open `/chat` and ask "What is NATO's Article 5?". Wait for the answer.
2. In the same conversation, send "Write me a report on what we have covered." Wait for the outline card, which pauses for approval.
3. Send "approve". Wait for the answer.

## Expected results
- The streamed progress for step 2 includes "Reading the conversation...".
- An outline card appears with a numbered list of at least one section.
- The streamed progress for step 3 includes "Writing the report...".
- The final answer is a new article and is not empty.
- No error bubble is shown.
