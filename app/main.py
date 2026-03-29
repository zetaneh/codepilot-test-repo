from datetime import datetime
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
async def health_check():
    return {"status": "ok", "checked_at": datetime.utcnow().isoformat(timespec='seconds') + "Z"}
