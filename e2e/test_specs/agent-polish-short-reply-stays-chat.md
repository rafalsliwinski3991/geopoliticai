# A short Polish reply stays a free Polish chat turn

## Preconditions
- Logged in as the E2E test user.

## Steps
1. Open `/chat` and note the meter's used count.
2. Send "Cześć". Wait for the answer.
3. In the same conversation, send "Dziękuję". Wait for the answer.

## Expected results
- Both answers are not empty, contain no link, and show no error bubble.
- The second answer is a new article and contains at least one Polish letter (ą, ć, ę, ł, ń, ó, ś, ź or ż), so it is not in English.
- Neither answer contains "What next?", and no research progress list stays visible.
- The streamed progress never includes "Searching and reading sources...".
- The meter shows the same number used as in step 1.
