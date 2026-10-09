"""Client for the internal, offline diagnosis terminology service."""

import httpx

from smartmed.backend_settings import BackendSettings


class TerminologyUnavailable(Exception):
    pass


class TerminologyTimeout(Exception):
    pass


class CodeNotFound(Exception):
    pass


class TerminologyClient:
    def __init__(self, settings: BackendSettings, transport=None):
        self.http = httpx.AsyncClient(
            base_url=settings.terminology_url,
            timeout=settings.terminology_timeout_s,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    async def close(self):
        await self.http.aclose()

    async def _get(self, path: str, **params) -> dict:
        try:
            response = await self.http.get(path, params=params)
            if response.status_code == 404:
                raise CodeNotFound
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict) or not isinstance(result.get("source"), dict):
                raise ValueError("Invalid terminology response")
            return result
        except httpx.TimeoutException as exc:
            raise TerminologyTimeout from exc
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise TerminologyUnavailable from exc

    async def catalog(self) -> dict:
        return await self._get("/v1/catalog")

    async def search(self, query: str, limit: int) -> dict:
        return await self._get("/v1/diagnoses/search", q=query, limit=limit)

    async def lookup(self, code: str) -> dict:
        return await self._get("/v1/diagnoses/lookup", code=code)
