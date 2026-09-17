"""FastAPI 앱 진입점 (T-210).

스캐폴드 단계에서는 /health 만 동작한다. 나머지 라우트는 routes.py에서 추가.
"""

from __future__ import annotations

from fastapi import FastAPI

from matcause import __version__
from .routes import router

app = FastAPI(title="MatCause", version=__version__)
app.include_router(router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


def run() -> None:
    """`matcause-api` 콘솔 스크립트 진입점."""
    import uvicorn

    uvicorn.run("matcause.api.main:app", host="127.0.0.1", port=8000, reload=True)
