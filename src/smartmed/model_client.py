"""Instructor validation over native Ollama. No OpenAI network client is created."""

import asyncio
import copy
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass

import httpx
import instructor
from instructor.core.exceptions import InstructorRetryException
from openai.types.chat import ChatCompletion
from tenacity import AsyncRetrying, stop_after_attempt

from smartmed.backend_settings import BackendSettings
from smartmed.prompt import PROMPT_VERSION, SYSTEM_PROMPT
from smartmed.schemas.extraction import Extraction, ExtractRequest, validate_extraction


class ModelUnavailable(Exception):
    pass


class GenerationTimeout(Exception):
    pass


class InvalidGeneration(Exception):
    pass


class ModelBusy(Exception):
    pass


def grounded_schema(schema: dict, request: ExtractRequest) -> dict:
    """Restrict generated citations to immutable patient spans and their exact IDs.

    Values still need runtime checking; span selection does not prove meaning.
    Never mutate Instructor's shared/cached schema with one patient's data.
    """
    result = copy.deepcopy(schema)
    alternatives = []
    for turn in request.turns:
        if turn.speaker != "patient":
            continue
        spans = list(dict.fromkeys([
            turn.text,
            *re.findall(r"[^，。！？；\n]+[，。！？；]?", turn.text),
        ]))
        alternatives.append({
            "type": "object", "additionalProperties": False,
            "required": ["turn_id", "quote"],
            "properties": {
                "turn_id": {"type": "integer", "const": turn.turn_id},
                "quote": {"type": "string", "enum": spans},
            },
        })
    if alternatives:
        result["$defs"]["Evidence"] = {"anyOf": alternatives}
    return result


@dataclass
class ExtractionResult:
    document: Extraction
    metadata: dict


class OllamaExtractor:
    def __init__(self, settings: BackendSettings, transport=None):
        # Instructor's retry errors can contain rejected clinical input.
        logging.getLogger("instructor").setLevel(logging.CRITICAL)
        self.settings = settings
        self.http = httpx.AsyncClient(
            base_url=settings.ollama_url,
            timeout=settings.timeout_s,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self.lock = asyncio.Lock()

    async def close(self):
        await self.http.aclose()

    async def health(self) -> dict:
        try:
            response = await self.http.get("/api/tags", timeout=3)
            response.raise_for_status()
            model = next(
                (m for m in response.json()["models"] if m["name"] == self.settings.model),
                None,
            )
            return {
                "ollama_available": True,
                "model_installed": model is not None,
                "model": self.settings.model,
                "digest": model.get("digest") if model else None,
                "busy": self.lock.locked(),
            }
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return {
                "ollama_available": False,
                "model_installed": False,
                "model": self.settings.model,
                "digest": None,
                "busy": self.lock.locked(),
            }

    async def extract(self, request: ExtractRequest) -> ExtractionResult:
        # A single local GPU: reject a parallel request instead of hiding queue latency.
        if self.lock.locked():
            raise ModelBusy
        async with self.lock:
            try:
                async with asyncio.timeout(self.settings.timeout_s):
                    return await self._extract(request)
            except TimeoutError as exc:
                raise GenerationTimeout from exc

    async def _extract(self, request: ExtractRequest) -> ExtractionResult:
        health = await self.health()
        if not health["ollama_available"] or not health["model_installed"]:
            raise ModelUnavailable
        attempts = []
        started = time.monotonic()

        async def native_completion(**kwargs) -> ChatCompletion:
            # Instructor prepares schema/retry feedback. Translate its in-memory
            # OpenAI-shaped request to Ollama's native API to enforce think:false.
            schema = grounded_schema(
                kwargs["response_format"]["json_schema"]["schema"], request,
            )
            payload = {
                "model": self.settings.model,
                "messages": kwargs["messages"],
                "format": schema,
                "think": False,
                "stream": False,
                "keep_alive": "5m",
                "options": {
                    "temperature": 0,
                    "seed": 42,
                    "num_ctx": self.settings.context_tokens,
                    "num_predict": self.settings.output_tokens,
                },
            }
            response = await self.http.post("/api/chat", json=payload)
            response.raise_for_status()
            raw = response.json()
            if raw.get("done") is not True or raw.get("done_reason") != "stop":
                raise InvalidGeneration
            content = raw["message"]["content"]
            if not isinstance(content, str):
                raise InvalidGeneration
            if raw.get("prompt_eval_count", 0) >= self.settings.context_tokens:
                raise InvalidGeneration
            attempts.append({
                "done_reason": raw.get("done_reason"),
                "prompt_tokens": raw.get("prompt_eval_count"),
                "output_tokens": raw.get("eval_count"),
                "total_duration_ns": raw.get("total_duration"),
            })
            return ChatCompletion(
                id="local-ollama",
                object="chat.completion",
                created=int(time.time()),
                model=self.settings.model,
                choices=[{
                    "index": 0,
                    "finish_reason": "length" if raw.get("done_reason") == "length" else "stop",
                    "message": {"role": "assistant", "content": content},
                }],
            )

        create = instructor.patch(create=native_completion, mode=instructor.Mode.JSON_SCHEMA)
        try:
            document = await create(
                response_model=Extraction,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(
                        {"turns": [turn.model_dump() for turn in request.turns]},
                        ensure_ascii=False,
                    )},
                ],
                context={"turns": request.turns},
                max_retries=AsyncRetrying(
                    stop=stop_after_attempt(self.settings.repair_attempts + 1), reraise=True,
                ),
                strict=True,
            )
            # Repeat grounding explicitly at the trust boundary, even if a future
            # Instructor release changes how validation context is propagated.
            document = validate_extraction(document.model_dump(), request.turns)
        except httpx.TimeoutException as exc:
            raise GenerationTimeout from exc
        except httpx.HTTPError as exc:
            raise ModelUnavailable from exc
        except InstructorRetryException as exc:
            causes = (exc, exc.__cause__, getattr(exc, "last_exception", None))
            if any(isinstance(cause, httpx.TimeoutException) for cause in causes):
                raise GenerationTimeout from exc
            if any(isinstance(cause, httpx.HTTPError) for cause in causes):
                raise ModelUnavailable from exc
            raise InvalidGeneration from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise InvalidGeneration from exc
        return ExtractionResult(document=document, metadata={
            "model": self.settings.model,
            "digest": health["digest"],
            "prompt_version": PROMPT_VERSION,
            "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
            "think": False,
            "context_tokens": self.settings.context_tokens,
            "output_tokens": self.settings.output_tokens,
            "temperature": 0,
            "seed": 42,
            "attempts": attempts,
            "elapsed_s": round(time.monotonic() - started, 3),
        })
