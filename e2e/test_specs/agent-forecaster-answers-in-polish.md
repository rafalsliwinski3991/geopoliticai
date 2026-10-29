# A Polish forecast answers in Polish with working links

## Preconditions
- Logged in as the E2E test user, with at least 20 research units left.

## Steps
1. Open `/chat` and note the meter's used count.
2. Ask "Zrób prognozę: czy NATO przyjmie nowego członka do 2028 roku?" Wait up to 900 s for the answer.

## Expected results
- The answer is not empty and contains the heading "Jak głosowała rada" and at least one "Twierdzenie" heading.
- It contains none of the English headings "How the council voted", "Council verdict" or "voted for".
- It contains at least one link, and every link's href starts with `https://`.
- The analysis's prose contains no "source:", and the vote list names its sources as "Źródło" with a number.
- No error bubble is shown.
- The meter shows 20 more used than in step 1.
- The streamed progress includes "Council voting, round 1 of 2...", so the forecaster ran.
