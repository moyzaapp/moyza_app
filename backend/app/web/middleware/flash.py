from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.web.utils.flash import FLASH_COOKIE_NAME
from app.web.utils.flash import decode_flash


class FlashMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        raw = request.cookies.get(FLASH_COOKIE_NAME)
        request.state.flash_messages = decode_flash(raw)

        response = await call_next(request)

        if raw:
            response.delete_cookie(FLASH_COOKIE_NAME, path="/")

        return response
