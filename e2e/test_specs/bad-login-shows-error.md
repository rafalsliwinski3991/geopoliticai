# Bad login shows an error

## Preconditions
- Not logged in.

## Steps
1. Open `/accounts/login/`.
2. Enter an email that has no account (`nobody@example.com`) and a wrong password, then press `Sign in`. A wrong password for the real test user could trip the login lockout and break later runs.

## Expected results
- The page stays on the login form.
- A visible error message appears: "The email address and/or password you specified are not correct."
- `/chat` is not reached.
