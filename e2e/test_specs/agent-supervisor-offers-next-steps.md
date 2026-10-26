# The supervisor offers next steps after a research answer

## Preconditions
- Logged in as the E2E test user, with at least 1 research unit left.

## Steps
1. Open `/chat`.
2. Send "What is NATO's Article 5?". Wait for the answer.

## Expected results
- The answer is not empty and shows no error bubble.
- The answer ends with a "What next?" footer.
- The footer names turn costs: it contains "research turn".
- The streamed progress includes "Searching and reading sources...", so the expert ran before the footer.
- The meter shows 1 more used than before the question: the footer itself costs nothing.
