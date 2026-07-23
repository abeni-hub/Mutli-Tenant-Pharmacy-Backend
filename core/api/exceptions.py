from collections.abc import Mapping
from typing import Any

from rest_framework.views import exception_handler


def api_exception_handler(exc: Exception, context: Mapping[str, Any]) -> Any:
    response = exception_handler(exc, context)
    if response is not None:
        response.data = {"error": response.data}
    return response
