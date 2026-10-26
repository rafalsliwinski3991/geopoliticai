# A plain follow-up stays on the expert

## Preconditions
- Logged in as the E2E test user, with at least 2 research units left.

## Steps
1. Open `/chat` and note the meter's used count.
2. Send "What is NATO's Article 5?". Wait for the answer.
3. In the same conversation, send "Which country was the first to invoke it?". Wait for the answer.

## Expected results
- Both answers are not empty and show no error bubble.
- The second answer is a new article and contains at least one link.
- The streamed progress after the second question includes "Searching and reading sources...".
- The streamed progress never includes "Council voting, round 1 of 2...".
- The meter shows 2 more used than in step 1: two expert turns, so the follow-up did not become a deep (10) or forecast (20) turn.
