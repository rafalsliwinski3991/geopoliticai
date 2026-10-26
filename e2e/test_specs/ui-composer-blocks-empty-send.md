# The question box ignores an empty message

## Preconditions
- Logged in as the E2E test user.

## Steps
1. Open `/chat` and note the meter's used count.
2. Press `Send` with the question box empty.
3. Type only spaces into the question box and press `Send`.

## Expected results
- Nothing is sent: the conversation holds no answer and no research progress list.
- The meter's used count is unchanged.
- No error message is shown.
