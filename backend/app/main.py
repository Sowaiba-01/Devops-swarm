"""
FastAPI application.

Wiring only: middleware, routers, lifecycle. Endpoint logic lives under
`app/api/`, persistence under `app/db/`, execution under `app/services/`.
"""

from __future__ import annotations

import asyncio
import contextlib
import time

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api import runs as runs_router
from app.api import stream as stream_router
from app.api import webhooks as webhooks_router
from app.config import settings
from app.core import metrics
from app.core.logging import configure_logging, get_logger, new_request_id, request_id_var
from app.core.redaction import redact
from app.db import repository
from app.db.database import check_connection, dispose_engine
from app.schemas import HealthResponse
from app.services.runner import executor
from app.tools.sandbox import reaper_loop
from app.tools.sandbox import registry as sandbox_registry
from app.ws_manager import manager

configure_logging()
logger = get_logger(__name__)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting %s v%s in %s", settings.SERVICE_NAME, settings.VERSION, settings.ENVIRONMENT
    )

    if not await check_connection():
        # Fail fast: a service that cannot reach its database has nothing to
        # serve, and starting anyway just turns a clear error into 500s.
        raise RuntimeError("Cannot reach the database. Check DATABASE_URL.")

    # Runs execute in-process, so anything still marked running at boot was
    # severed by the previous shutdown and has no executor behind it.
    orphaned = await repository.reconcile_orphaned_runs()
    if orphaned:
        logger.warning("Marked %d interrupted run(s) as failed", orphaned)

    background = [asyncio.create_task(reaper_loop(), name="sandbox-reaper")]

    try:
        yield
    finally:
        logger.info("Shutting down")
        for task in background:
            task.cancel()
        await asyncio.gather(*background, return_exceptions=True)

        await executor.drain(timeout=30.0)
        await manager.close_all()
        await asyncio.to_thread(sandbox_registry.release_all)
        await dispose_engine()
        logger.info("Shutdown complete")


app = FastAPI(
    title="DevOps Swarm API",
    description=(
        "Multi-agent system that plans, implements, tests and reviews changes for "
        "GitHub issues, then opens a draft pull request."
    ),
    version=settings.VERSION,
    lifespan=lifespan,
    # Interactive docs are useful locally and are an information leak in prod.
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

# ── Middleware (executes bottom-up) ────────────────────────────────────

app.add_middleware(GZipMiddleware, minimum_size=1024)

if settings.is_production:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[
            h.replace("https://", "").replace("http://", "").split("/")[0]
            for h in settings.cors_origins_list
        ]
        + ["*.internal"],
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
    max_age=600,
)


@app.middleware("http")
async def observability_middleware(request: Request, call_next) -> Response:
    """Assign a request id, record RED metrics, and log the outcome."""
    request_id = request.headers.get("X-Request-ID") or new_request_id()
    token = request_id_var.set(request_id)
    started = time.perf_counter()

    # Label on the route *template* — labelling on the raw path would create an
    # unbounded set of Prometheus series, one per run id.
    route = request.scope.get("route")
    route_label = getattr(route, "path", request.url.path)

    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception:
        status_code = 500
        logger.exception("Unhandled error serving %s %s", request.method, request.url.path)
        response = JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "request_id": request_id},
        )
    finally:
        elapsed = time.perf_counter() - started
        route_label = getattr(request.scope.get("route"), "path", route_label)
        metrics.http_requests_total.labels(
            method=request.method, route=route_label, status=f"{status_code // 100}xx"
        ).inc()
        metrics.http_request_duration.labels(method=request.method, route=route_label).observe(
            elapsed
        )
        request_id_var.reset(token)

    response.headers["X-Request-ID"] = request_id
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


# ── Error handlers ─────────────────────────────────────────────────────


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": redact(str(exc.detail)), "request_id": request_id_var.get()},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Request validation failed",
            "errors": [
                {"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]}
                for e in exc.errors()
            ],
            "request_id": request_id_var.get(),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s", request.url.path)
    # Never return the exception text: it can carry credentials and internals.
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id_var.get()},
    )


# ── Routers ────────────────────────────────────────────────────────────

app.include_router(runs_router.router)
app.include_router(webhooks_router.router)
app.include_router(stream_router.router)


# ── Operational endpoints ──────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse, tags=["ops"], summary="Readiness probe")
async def health() -> HealthResponse:
    """
    Readiness, not just liveness.

    The previous handler returned a hardcoded `{"status": "ok"}`, so an orchestrator
    kept routing traffic to a replica whose database was gone.
    """
    db_up = await check_connection()
    return HealthResponse(
        status="ok" if db_up else "degraded",
        version=settings.VERSION,
        environment=settings.ENVIRONMENT,
        database="up" if db_up else "down",
        runs_in_flight=executor.in_flight,
        sandboxes_active=len(sandbox_registry),
    )


@app.get("/health/live", tags=["ops"], summary="Liveness probe")
async def liveness() -> dict:
    """Process is up. Deliberately does no I/O so a slow dependency cannot
    trigger a restart loop."""
    return {"status": "alive"}


@app.get("/metrics", tags=["ops"], include_in_schema=False)
async def prometheus_metrics() -> Response:
    return Response(content=metrics.render(), media_type=metrics.CONTENT_TYPE_LATEST)


@app.get("/", tags=["ops"], include_in_schema=False)
async def root() -> dict:
    return {
        "service": settings.SERVICE_NAME,
        "version": settings.VERSION,
        "docs": None if settings.is_production else "/docs",
        "health": "/health",
    }


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(
        "app.main:app",
        # Binding to all interfaces is intentional: the process runs inside a
        # container and is reached through its published port.
        host="0.0.0.0",  # noqa: S104
        port=8000,
        reload=not settings.is_production,
    )
