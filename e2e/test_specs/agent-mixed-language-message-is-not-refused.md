# A Polish message with an English phrase is answered, not refused

## Preconditions
- Logged in as the E2E test user, with at least 1 research unit left.

## Steps
1. Open `/chat` and note the meter's used count.
2. Send "Czy NATO zwiększy wydatki na obronę po latest summit?". Wait for the answer.

## Expected results
- The answer is not empty, contains at least one link, and shows no error bubble.
- The answer does not contain "supports only English and Polish".
- The streamed progress includes "Searching and reading sources...", so the expert ran.
- The meter shows exactly 1 more used than in step 1.
