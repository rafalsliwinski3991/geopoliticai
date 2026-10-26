# A forecast answers with working links
## Preconditions
- Logged in as the E2E test user, with at least 20 research units left.
## Steps
1. Open `/chat` and note the meter's used count.
2. Ask "Forecast whether NATO will admit a new member by 2028." Wait up to 900 s for the answer.
## Expected results
- The answer is not empty and contains the heading "How the council voted".
- It contains at least one link, and every link's href starts with `https://`.
- Every link in the answer is a real URL, and the analysis's prose contains no "source:".
- No error bubble is shown.
- The meter shows 20 more used than in step 1.
- The streamed progress includes "Council voting, round 1 of 2...", so the forecaster ran.
