from fastapi import FastAPI

app = FastAPI(title="GeoHorizon API", version="0.1.1")


@app.get("/health")
async def health():
    return {"status": "ok"}
