"""
Custom exceptions for backend operations.
Makes it easy to catch and log specific error types.
"""


class BackendError(Exception):
    """Base exception for all backend errors."""
    pass


class BackendConnectionError(BackendError):
    """Database or storage connection failed."""
    def __init__(self, backend: str, message: str, details: dict = None):
        self.backend = backend
        self.message = message
        self.details = details or {}
        super().__init__(f"[{backend}] Connection error: {message}")


class BackendQueryError(BackendError):
    """Database query failed."""
    def __init__(self, backend: str, query: str, message: str, details: dict = None):
        self.backend = backend
        self.query = query
        self.message = message
        self.details = details or {}
        super().__init__(f"[{backend}] Query error: {message}")


class BackendStorageError(BackendError):
    """File upload/download failed."""
    def __init__(self, backend: str, operation: str, filename: str, message: str, details: dict = None):
        self.backend = backend
        self.operation = operation
        self.filename = filename
        self.message = message
        self.details = details or {}
        super().__init__(f"[{backend}] Storage {operation} failed for {filename}: {message}")


class BackendNotInitializedError(BackendError):
    """Backend client accessed before initialization."""
    def __init__(self, backend_type: str):
        super().__init__(f"{backend_type} client not initialized. Call init_backends() at startup.")


class BackendValidationError(BackendError):
    """Data validation failed before database operation."""
    def __init__(self, field: str, value: any, expected: str):
        self.field = field
        self.value = value
        self.expected = expected
        super().__init__(f"Validation error: {field} = {value}, expected {expected}")


class AnalysisNotFoundError(BackendError):
    """Analysis record not found."""
    def __init__(self, analysis_id: str):
        self.analysis_id = analysis_id
        super().__init__(f"Analysis {analysis_id} not found")


class UserNotFoundError(BackendError):
    """User record not found."""
    def __init__(self, user_id: str):
        self.user_id = user_id
        super().__init__(f"User {user_id} not found")


class CacheKeyNotFoundError(BackendError):
    """No analysis found for cache key."""
    def __init__(self, cache_key: str):
        self.cache_key = cache_key
        super().__init__(f"No cached analysis found for {cache_key}")
