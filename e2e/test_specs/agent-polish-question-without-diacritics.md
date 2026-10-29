# A Polish question typed without diacritics still gets a Polish answer

## Preconditions
- Logged in as the E2E test user, with at least 1 research unit left.

## Steps
1. Open `/chat` and note the meter's used count.
2. Send "Czy ukraina moze wygrac z rosja?". Wait for the answer.

## Expected results
- The answer is not empty, contains at least one link, and shows no error bubble.
- The answer contains at least one Polish letter (ą, ć, ę, ł, ń, ó, ś, ź or ż) and ends with a "Co dalej?" footer, so it is not in English.
- The answer does not contain "What next?" or "supports only English and Polish", so the question was not refused.
- The streamed progress includes "Searching and reading sources...", so the expert ran.
- The meter shows exactly 1 more used than in step 1.
