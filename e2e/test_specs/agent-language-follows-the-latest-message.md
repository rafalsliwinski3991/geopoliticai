# The answer language follows the latest message when a conversation switches language

## Preconditions
- Logged in as the E2E test user, with at least 2 research units left.

## Steps
1. Open `/chat` and note the meter's used count.
2. Send "Czym jest Artykuł 5 NATO?". Wait for the answer.
3. In the same conversation, send "What is NATO's Article 3?". Wait for the answer.

## Expected results
- Both answers are not empty, contain at least one link, and show no error bubble.
- The first answer ends with a "Co dalej?" footer and does not contain "What next?".
- The second answer ends with a "What next?" footer and does not contain "Co dalej?".
- The streamed progress for each step includes "Searching and reading sources...".
- The meter shows 2 more used than in step 1.
