"""Local ASR service client. Audio never goes to an external model API."""

import httpx

from smartmed.backend_settings import BackendSettings


class ASRUnavailable(Exception):
    pass


class ASRTimeout(Exception):
    pass


class ASRInvalidAudio(Exception):
    pass


class ASRClient:
    def __init__(self, settings: BackendSettings, transport=None):
        self.http = httpx.AsyncClient(
            base_url=settings.asr_url,
            timeout=settings.asr_timeout_s,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    async def close(self):
        await self.http.aclose()

    async def transcribe(self, audio: bytes) -> dict:
        try:
            response = await self.http.post(
                "/v1/transcribe", content=audio, headers={"Content-Type": "audio/wav"}
            )
            if response.status_code == 422:
                raise ASRInvalidAudio
            response.raise_for_status()
            result = response.json()
            if not isinstance(result.get("text"), str):
                raise ValueError("ASR response has no text")
            return result
        except httpx.TimeoutException as exc:
            raise ASRTimeout from exc
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ASRUnavailable from exc
