# Second conversation keeps the first

## Preconditions
- Logged in as the E2E test user.

## Steps
1. Open `/chat` and ask "What is NATO's Article 5?". Wait for the answer.
2. Start a new conversation from the sidebar.
3. Reload the page.

## Expected results
- The new conversation is empty.
- The first conversation is still listed in the sidebar.
- Opening it shows its answer again.
