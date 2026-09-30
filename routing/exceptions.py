from rest_framework.exceptions import APIException
from rest_framework.views import exception_handler as drf_handler


class RouteError(APIException):
    status_code = 422
    default_code = "route_unavailable"

    def __init__(self, code, message, status=422):
        self.status_code = status
        self.error_code = code
        super().__init__(message, code=code)


def exception_handler(exc, context):
    response = drf_handler(exc, context)
    if response is not None:
        response.data = {
            "error": {
                "code": getattr(
                    exc, "error_code", getattr(exc, "default_code", "invalid_request")
                ),
                "message": str(exc.detail)
                if isinstance(exc, RouteError)
                else "The request could not be completed.",
                "details": response.data,
            }
        }
    return response
