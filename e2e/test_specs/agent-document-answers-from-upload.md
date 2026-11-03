# Answer a question from an uploaded document

## Preconditions
- Logged in as the E2E test user.

## Steps
1. Open `/chat` and start a new conversation.
2. Choose the Attach button and pick a small text file named `harbor-notes.txt` that holds one sentence: "The Kestrel Harbor ferry timetable changed to 7 departures a day in 2031."
3. Wait for the file name to appear above the question box.
4. Ask "How many departures a day does the Kestrel Harbor ferry have?" and wait for the answer.
5. Remove the document with its Remove button, so the test user keeps no file behind: the cap is 5 documents.

## Expected results
- After step 3 the chip shows `harbor-notes.txt` and the footer says "Answers come from your document while one is attached."
- The answer contains "7".
- The answer contains a citation in the form `[excerpt 1]`: a text file has no pages, so the citation is the excerpt number, without the file name.
- No error message is shown.
- After step 5 the chip is gone and the footer no longer mentions the document.
