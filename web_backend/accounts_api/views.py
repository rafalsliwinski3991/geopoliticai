"""The session-cookie to JWT exchange the chat SPA calls on load."""

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from rest_framework_simplejwt.tokens import AccessToken

# Only an access token is minted. The same-origin session cookie already *is*
# the long-lived credential, so a refresh token would be a second one with a
# second revocation story; the SPA re-calls this endpoint instead. See the
# plan's §7 for the flag-2 deviation this records.


def token(request: HttpRequest) -> JsonResponse:
    """Return a short-lived access token for the session's user.

    Returns JSON 401 rather than redirecting to the login page: the caller is
    `fetch()` inside the SPA, which cannot follow an HTML redirect usefully and
    must decide for itself to send the browser to `/accounts/login/?next=/chat`
    (brainstorm flag 12).
    """
    user = request.user
    if not user.is_authenticated or not user.is_active:
        return JsonResponse({"detail": "Not authenticated."}, status=401)
    # `AccessToken.for_user` does not itself check `is_active`; the guard above
    # is that check (simplejwt, docs/creating_tokens_manually.md).
    return JsonResponse(
        {
            "access": str(AccessToken.for_user(user)),
            "expires_in": settings.ACCESS_TOKEN_SECONDS,
        }
    )
