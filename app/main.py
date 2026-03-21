"""
Simple Todo API — target repo for CodePilot agent testing.
"""
from fastapi import FastAPI
from app.routers import todos, users

app = FastAPI(title="Todo API", version="0.1.0")

app.include_router(todos.router, prefix="/todos", tags=["todos"])
app.include_router(users.router, prefix="/users", tags=["users"])


@app.get("/health")
def health():
    return {"status": "ok"}
