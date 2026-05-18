from fastapi import FastAPI

from app.config import load_config
from app.models import ScanRequest, ScanResponse
from app.scanner import scan_tickers

app = FastAPI(title="Project Orion", version="0.1.0", description="Swing trade scanner")


@app.post("/scan", response_model=ScanResponse)
async def scan(request: ScanRequest) -> ScanResponse:
    tickers = [t.upper() for t in request.tickers]
    results, errors, _ = scan_tickers(tickers, min_rr=request.min_rr)
    return ScanResponse(results=results, errors=errors)


@app.get("/config")
async def get_config() -> dict:
    return load_config()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
