"""
Simple Todo API — target repo for CodePilot agent testing.
"""
import logging

from fastapi import FastAPI

from app.core.rate_limit_middleware import RateLimitMiddleware
from app.routers import todos, users
from app.routers import runs

logger = logging.getLogger(__name__)

app = FastAPI(title="Todo API", version="0.1.0")

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

app.add_middleware(RateLimitMiddleware)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(todos.router, prefix="/todos", tags=["todos"])
app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(runs.router, prefix="/api/runs", tags=["runs"])


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
