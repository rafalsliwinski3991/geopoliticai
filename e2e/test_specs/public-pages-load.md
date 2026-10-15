# Public pages load

## Preconditions
- Not logged in.

## Steps
1. Open `/`, `/about/`, `/privacy/`, `/accounts/login/`, `/robots.txt`, `/sitemap.xml` and `/llms.txt`.
2. Request `/api/health`.

## Expected results
- Each page answers 200 and shows a heading (the text files are not empty).
- No page logs a console error.
- No request on the pages fails (no 4xx or 5xx for fonts, CSS or JS).
- `/api/health` answers 200.
