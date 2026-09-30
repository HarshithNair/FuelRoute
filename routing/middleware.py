import logging
from time import perf_counter

logger = logging.getLogger("routing")


class TimingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = perf_counter()
        response = self.get_response(request)
        elapsed = (perf_counter() - started) * 1000
        response["Server-Timing"] = f"app;dur={elapsed:.1f}"
        if request.path.startswith("/api/"):
            logger.info(
                "%s %s status=%s elapsed_ms=%.1f",
                request.method,
                request.path,
                response.status_code,
                elapsed,
            )
        return response
