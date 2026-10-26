# Reopening an earlier conversation loads its history

## Preconditions
- Logged in as the E2E test user.

## Steps
1. Open `/chat` and ask "What is NATO's Article 5?". Wait for the answer.
2. Start a new conversation from the sidebar.
3. Open the first conversation from the sidebar.
4. Reload the page.

## Expected results
- After step 3 the page heading is the question, and the conversation shows the question you asked and its answer.
- The reopened answer is not empty and contains at least one link.
- No error message is shown and no research progress list is visible.
- After the reload the same conversation is still open with the same question and a non-empty answer.
