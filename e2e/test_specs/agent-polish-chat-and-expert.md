# Polish welcome message, chat greeting, and expert answer

## Preconditions
- Logged in as the E2E test user.

## Steps
1. Open `/chat`.
2. Send "Cześć". Wait for the answer.
3. In the same conversation, send "Czym jest Artykuł 5 NATO?". Wait for the answer.

## Expected results
- Before sending any message, the welcome message is visible, includes "Możesz rozmawiać ze mną po angielsku lub po polsku.", and the conversation holds no answer article.
- After step 2, the first answer article is not empty, contains no link, and the daily research meter shows the same number of turns used as before step 2.
- After step 3, the second answer is a new article, is not empty, and contains at least one link.
- The streamed progress for step 3 includes "Searching and reading sources...", so the expert agent ran.
- No error message is shown.
