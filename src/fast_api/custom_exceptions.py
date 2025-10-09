# file:src/fast_api_utils/custom_exceptions.py
from fastapi import HTTPException, status

class CustomHTTPException(HTTPException):
    def __init__(self, status_code: int, error: str, detail: str = None):
        super().__init__(
            status_code=status_code,
            detail={"error": error, "detail": detail or error}
        )

class NotFoundException(CustomHTTPException):
    def __init__(self, detail: str = "Resource not found"):
        super().__init__(status.HTTP_404_NOT_FOUND, "Not Found", detail)

class UnauthorizedException(CustomHTTPException):
    def __init__(self, detail: str = "Authentication required"):
        super().__init__(status.HTTP_401_UNAUTHORIZED, "Unauthorized", detail)

class ForbiddenException(CustomHTTPException):
    def __init__(self, detail: str = "Access denied"):
        super().__init__(status.HTTP_403_FORBIDDEN, "Forbidden", detail)

class ValidationException(CustomHTTPException):
    def __init__(self, detail: str = "Validation failed"):
        super().__init__(status.HTTP_422_UNPROCESSABLE_ENTITY, "Validation Error", detail)

class RateLimitException(CustomHTTPException):
    def __init__(self, detail: str = "Rate limit exceeded"):
        super().__init__(status.HTTP_429_TOO_MANY_REQUESTS, "Rate Limit Exceeded", detail)

class InternalServerException(CustomHTTPException):
    def __init__(self, detail: str = "Internal server error"):
        super().__init__(status.HTTP_500_INTERNAL_SERVER_ERROR, "Internal Server Error", detail)
