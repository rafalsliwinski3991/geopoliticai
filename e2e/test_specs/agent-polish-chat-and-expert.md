# Polish welcome message, chat greeting, expert answer, and language refusal

## Preconditions
- Logged in as the E2E test user, with at least 1 research unit left.

## Steps
1. Open `/chat`.
2. Send "Cześć". Wait for the answer.
3. In the same conversation, send "Czym jest Artykuł 5 NATO?". Wait for the answer.
4. In the same conversation, send "Was ist Artikel 5 der NATO?". Wait for the answer.
5. Click "New conversation".

## Expected results
- Before sending any message, the welcome message is visible, includes "Możesz rozmawiać ze mną po angielsku lub po polsku.", and the conversation holds no answer article.
- After step 2, the welcome message is gone, the first answer article is not empty, contains no link, and the daily research meter shows the same number of turns used as before step 2.
- After step 3, the second answer is a new article, is not empty, contains at least one link, and contains at least one Polish letter (ą, ć, ę, ł, ń, ó, ś, ź or ż), so it is not in English.
- After step 3, the second answer ends with a "Co dalej?" footer that contains "tur", and the meter shows 1 more turn used than after step 2.
- The streamed progress for step 3 includes "Searching and reading sources...", so the expert agent ran.
- After step 4, the third answer is a new article, is not empty, contains no link, and mentions "Polish". The meter shows the same number of turns used as after step 3, and the streamed progress for step 4 never includes "Searching and reading sources...".
- After step 5, the welcome message is visible again and the conversation holds no answer article.
- No error message is shown at any point.
