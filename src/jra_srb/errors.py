from __future__ import annotations


class JraApiError(RuntimeError):
    status_code = 500

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class BadRequestError(JraApiError):
    status_code = 400


class ResourceNotFoundError(JraApiError):
    status_code = 404


class UpstreamServiceError(JraApiError):
    status_code = 502
