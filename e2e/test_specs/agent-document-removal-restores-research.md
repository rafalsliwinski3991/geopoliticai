# Removing a document brings back research answers

## Preconditions
- Logged in as the E2E test user.

## Steps
1. Open `/chat` and start a new conversation.
2. Choose the Attach button and pick a small text file named `harbor-notes.txt` that holds one sentence: "The Kestrel Harbor ferry timetable changed to 7 departures a day in 2031."
3. Wait for the file name to appear above the question box.
4. Remove the document with its Remove button.
5. Type "What is NATO's Article 5?" into the question box and send it.
6. Wait for the answer to finish.

## Expected results
- After step 4 the chip is gone.
- The answer text is not empty.
- The answer contains at least one link.
- No error message is shown.
- The streamed progress includes "Searching and reading sources...", so the expert agent ran and not the document agent.
