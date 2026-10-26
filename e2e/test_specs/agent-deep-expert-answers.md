# Deep dive answers

## Preconditions
- Logged in as the E2E test user, with at least 10 research units left.

## Steps
1. Open `/chat`.
2. Ask "Give me a deep dive on the history of NATO's Article 5." Wait for the answer, up to 500 s: a deep turn runs up to 480 s and shows its answer only at the end.

## Expected results
- The answer is not empty.
- The answer contains at least one link.
- No error bubble is shown.
- The daily research meter shows 10 more turns used than before the question: a deep turn's cost (a plain
  answer would add 1).
- The streamed progress includes "Planning the research...", so the deep expert ran.
