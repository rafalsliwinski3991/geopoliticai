# Logout requires login

## Preconditions
- None. The test signs in in its own browser context, because logging out ends the server session and would break the other tests if it used the shared one.

## Steps
1. Sign in and open `/chat`.
2. Log out.
3. Open `/chat` again.

## Expected results
- After logout the home page is shown with a `Sign in` link and no `Sign out` link.
- Opening `/chat` sends you to the login page.
