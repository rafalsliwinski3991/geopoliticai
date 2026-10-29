# A message in another language is refused in English at no cost

## Preconditions
- Logged in as the E2E test user.

## Steps
1. Open `/chat` and note the meter's used count.
2. Send "¿Qué es el Artículo 5 de la OTAN?". Wait for the answer.

## Expected results
- The answer is not empty, contains no link, shows no error bubble, and contains "Polish".
- The answer does not contain "What next?".
- The streamed progress never includes "Searching and reading sources...".
- The meter shows the same number used as in step 1.
