from __future__ import annotations


class JraApiError(RuntimeError):
    status_code = 500
    error_code = "internal_error"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class BadRequestError(JraApiError):
    status_code = 400
    error_code = "bad_request"


class ResourceNotFoundError(JraApiError):
    status_code = 404
    error_code = "not_found"


class UpstreamServiceError(JraApiError):
    status_code = 502
    error_code = "upstream_error"
