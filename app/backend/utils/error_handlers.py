from fastapi import Request
from fastapi.exceptions import RequestValidationError, HTTPException
from fastapi.responses import JSONResponse
from starlette.status import HTTP_422_UNPROCESSABLE_ENTITY, HTTP_404_NOT_FOUND, HTTP_500_INTERNAL_SERVER_ERROR


# Validation error handler
def registerValidationHandler(app):
    @app.exception_handler(RequestValidationError)
    async def validationExceptionHandler(request: Request, exc: RequestValidationError):
        errors = []
        for err in exc.errors():
            field = ".".join(str(loc) for loc in err["loc"] if isinstance(loc, str))
            message = err["msg"]
            errors.append({"field": field, "message": message})
        return JSONResponse(
            status_code=HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": "Validation failed", "errors": errors}
        )


# Not found error handler
def registerNotFoundHandler(app):
    @app.exception_handler(HTTPException)
    async def notFoundHandler(request, exc):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail}
        )


# Internal server error handler
def registerServerErrorHandler(app):
    @app.exception_handler(Exception)
    async def serverErrorHandler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error", "error": str(exc)}
        )


# Register all handlers
def registerAllErrorHandlers(app):
    registerValidationHandler(app)
    registerNotFoundHandler(app)
    registerServerErrorHandler(app)
