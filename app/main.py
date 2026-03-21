"""
Simple Todo API — target repo for CodePilot agent testing.
"""
from fastapi import FastAPI
from app.routers import todos, users
from app.api.routes import runs

app = FastAPI(title="Todo API", version="0.1.0")

app.include_router(todos.router, prefix="/todos", tags=["todos"])
app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(runs.router, prefix="/api/runs", tags=["runs"])


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
