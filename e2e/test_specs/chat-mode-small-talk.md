# Chat mode small talk

## Preconditions
- Logged in as the E2E test user.

## Steps
1. Open `/chat`.
2. Send "Hi". Wait for the answer.
3. In the same conversation, send "What is the weather like today?". Wait for the answer.

## Expected results
- Each of the two answers is not empty.
- Neither answer shows an error bubble.
- Neither answer contains a link, because chat mode has no sources.
- No research progress list stays visible after either answer.
- The second answer is a new article, so the thread now holds two answers.
