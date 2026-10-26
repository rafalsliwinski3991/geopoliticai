# A forward-looking question does not start a forecast

## Preconditions
- Logged in as the E2E test user, with at least 1 research unit left.

## Steps
1. Open `/chat` and note the meter's used count.
2. Send "Which countries are in talks to join NATO, and how far along are they?". Wait for the answer.

## Expected results
- The answer is not empty, contains at least one link, and shows no error bubble.
- The answer does not contain "How the council voted".
- The streamed progress never includes "Council voting, round 1 of 2...", so the forecaster did not run.
- The meter shows exactly 1 more used than in step 1, not 20.
