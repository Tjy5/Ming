from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import logging

from api.routes import router
from api.save_routes import save_router
from api.settings_routes import settings_router
from api.assembly_routes import assembly_router
from api.admin_routes import admin_router
from api.chat_routes import chat_router
from api.state import startup as api_startup


@asynccontextmanager
async def lifespan(app: FastAPI):
    api_startup()
    yield


app = FastAPI(title="大明：危局", lifespan=lifespan)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logging.error(f"Validation error: {exc.errors()}")
    try:
        body = await request.json()
        logging.error(f"Request body: {body}")
    except Exception:
        logging.error("Could not read request body")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": str(exc.body)},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(save_router)
app.include_router(settings_router)
app.include_router(assembly_router)
app.include_router(admin_router)
app.include_router(chat_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
