from datetime import timedelta

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from starlette.requests import Request
from starlette.responses import Response

SESSION_COOKIE_NAME = "session"
SESSION_MAX_AGE = int(timedelta(days=30).total_seconds())


class SessionManager:
    def __init__(self, secret_key: str) -> None:
        self._serializer = URLSafeTimedSerializer(secret_key, salt="session")

    def set_session(self, response: Response, email: str) -> None:
        token = self._serializer.dumps({"email": email})
        response.set_cookie(
            SESSION_COOKIE_NAME,
            token,
            max_age=SESSION_MAX_AGE,
            httponly=True,
            samesite="none",
            secure=True,
        )

    def get_email(self, request: Request) -> str | None:
        cookie = request.cookies.get(SESSION_COOKIE_NAME)
        if not cookie:
            return None
        try:
            data: dict[str, str] = self._serializer.loads(cookie, max_age=SESSION_MAX_AGE)
            return data.get("email")
        except (BadSignature, SignatureExpired):
            return None

    def clear_session(self, response: Response) -> None:
        response.delete_cookie(SESSION_COOKIE_NAME)
