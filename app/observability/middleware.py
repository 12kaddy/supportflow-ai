from time import perf_counter
from uuid import uuid4

from app.observability.events import emit, request_id


class RequestTelemetryMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        identifier = uuid4().hex
        token = request_id.set(identifier)
        scope.setdefault("state", {})["request_id"] = identifier
        started = perf_counter()
        status = 500
        error_type = None

        async def traced_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != b"x-request-id"
                ]
                message = {**message, "headers": headers + [(b"x-request-id", identifier.encode())]}
            await send(message)

        try:
            await self.app(scope, receive, traced_send)
        except Exception as exc:
            error_type = type(exc).__name__
            raise
        finally:
            route = scope.get("route")
            emit(
                "http_request_completed",
                method=scope["method"],
                route=getattr(route, "path", "unmatched"),
                status=status,
                latency_ms=round((perf_counter() - started) * 1000, 2),
                error_type=error_type,
            )
            request_id.reset(token)
