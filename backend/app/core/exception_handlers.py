"""Global exception handlers for FastAPI — converts all unhandled exceptions to clean JSON responses."""

import logging
import traceback
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError, IntegrityError, DataError
from pydantic import ValidationError as PydanticValidationError

from app.config import settings

logger = logging.getLogger(__name__)


def register_exception_handlers(app: FastAPI) -> None:
    """Register all global exception handlers."""

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Clean 422 responses with field-level error details."""
        errors = []
        for err in exc.errors():
            loc = " → ".join(str(l) for l in err["loc"]) if err["loc"] else "unknown"
            errors.append({"field": loc, "message": err["msg"], "type": err["type"]})
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": "validation_error",
                "message": "Request validation failed",
                "details": errors,
            },
        )

    @app.exception_handler(PydanticValidationError)
    async def pydantic_validation_handler(request: Request, exc: PydanticValidationError):
        """Handle Pydantic validation errors from schemas."""
        errors = []
        for err in exc.errors():
            loc = " → ".join(str(l) for l in err["loc"]) if err["loc"] else "unknown"
            errors.append({"field": loc, "message": err["msg"], "type": err["type"]})
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": "validation_error",
                "message": "Data validation failed",
                "details": errors,
            },
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError):
        """Handle database integrity violations (duplicate key, FK constraint, etc)."""
        msg = str(exc.orig) if hasattr(exc, "orig") else str(exc)
        # Try to give a useful message
        if "duplicate key" in msg.lower():
            detail = "A record with this value already exists"
        elif "foreign key" in msg.lower():
            detail = "Referenced record does not exist"
        elif "unique constraint" in msg.lower():
            detail = "This value already exists"
        else:
            detail = "Database integrity constraint violated"
        logger.warning(f"IntegrityError on {request.method} {request.url}: {msg}")
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": "integrity_error",
                "message": detail,
            },
        )

    @app.exception_handler(DataError)
    async def data_error_handler(request: Request, exc: DataError):
        """Handle database data errors (e.g., too long, wrong type)."""
        msg = str(exc.orig) if hasattr(exc, "orig") else str(exc)
        logger.warning(f"DataError on {request.method} {request.url}: {msg}")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": "data_error",
                "message": "Invalid data provided",
                "detail": "Check field lengths and data types",
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
        """Catch-all for database errors — log and return clean 500."""
        logger.exception(f"Database error on {request.method} {request.url}: {exc}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "database_error",
                "message": "A database error occurred. Please try again.",
            },
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        """Handle business logic ValueErrors with a clean 400."""
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": "bad_request",
                "message": str(exc) or "Invalid request",
            },
        )

    @app.exception_handler(PermissionError)
    async def permission_error_handler(request: Request, exc: PermissionError):
        """Handle authorization failures."""
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "error": "forbidden",
                "message": str(exc) or "You don't have permission for this action",
            },
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Catch-all — log stack trace, return generic 500 to client."""
        logger.exception(
            f"Unhandled exception on {request.method} {request.url}: "
            f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        )
        # In debug mode, include more detail
        if settings.debug:
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "error": "internal_error",
                    "message": str(exc),
                    "type": type(exc).__name__,
                    "detail": traceback.format_exc(),
                },
            )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "internal_error",
                "message": "An unexpected error occurred. Please try again.",
            },
        )