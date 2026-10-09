"""Private, offline diagnosis lookup API. It never infers a diagnosis."""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query

from services.terminology.catalog import Catalog, normalize, source


def create_app(catalog: Catalog | None = None) -> FastAPI:
    catalog = catalog or Catalog(
        Path(os.getenv("SMARTMED_TERMINOLOGY_DB", "/app/catalog/diagnoses.sqlite3"))
    )
    app = FastAPI(title="SmartMed diagnosis terminology", version="0.1.0")

    @app.get("/health")
    def health():
        return {"status": "ready" if catalog.ready() else "catalog_missing"}

    @app.get("/v1/catalog")
    def catalog_info():
        if not catalog.ready():
            raise HTTPException(503, detail={"code": "catalog_unavailable"})
        return {"source": source(), "row_count": catalog.count()}

    @app.get("/v1/diagnoses/search")
    def search(q: str = Query(min_length=1, max_length=80), limit: int = Query(20, ge=1, le=50)):
        if not normalize(q):
            raise HTTPException(422, detail={"code": "empty_query"})
        if not catalog.ready():
            raise HTTPException(503, detail={"code": "catalog_unavailable"})
        matches, has_more = catalog.search(q, limit)
        return {"query": q, "matches": matches, "has_more": has_more, "source": source()}

    @app.get("/v1/diagnoses/lookup")
    def lookup(code: str = Query(min_length=1, max_length=40)):
        if not normalize(code):
            raise HTTPException(422, detail={"code": "empty_code"})
        if not catalog.ready():
            raise HTTPException(503, detail={"code": "catalog_unavailable"})
        matches = catalog.lookup(code)
        if not matches:
            raise HTTPException(404, detail={"code": "code_not_in_catalog"})
        return {"code": code, "matches": matches, "source": source()}

    return app


app = create_app()
