"""AWS Lambda handler for FastAPI application."""

import os

from mangum import Mangum

_handler = None
_initialize_services = None
_services_initialized = False


def _load_handler():
    """Create the Mangum adapter lazily for Lambda cold starts."""
    global _handler, _initialize_services

    if _handler is None:
        os.makedirs("/tmp/uploads", exist_ok=True)
        os.makedirs("/tmp/cached_chunks", exist_ok=True)

        from app.main import app, initialize_services

        _initialize_services = initialize_services
        _handler = Mangum(app, lifespan="off")

    return _handler, _initialize_services


def handler(event, context):
    """
    Lambda handler with lazy service initialization.
    Services are initialized on first request to avoid 10-second init timeout.
    """
    global _services_initialized
    lambda_handler, initialize_services = _load_handler()

    if not _services_initialized:
        initialize_services()
        _services_initialized = True

    return lambda_handler(event, context)
