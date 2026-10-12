from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

from backend.broker import connect, disconnect
import backend.events.listeners  # pylint: disable=unused-import
from backend.exceptions import AppError
from backend.routes import router, task_router, tenant_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await connect()
    yield
    await disconnect()


app = FastAPI(title="Tenant Provisioning Control Plane", lifespan=lifespan)

app.include_router(router)
app.include_router(tenant_router)
app.include_router(task_router)


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code if exc.status_code else 400,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "Validation errors",
            },
            "detail": exc.errors(),
        },
    )
