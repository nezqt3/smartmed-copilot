"""Instructor JSON-schema extraction for outpatient.v1, sharing the local model lock."""

import hashlib
import json
import re
import time
from dataclasses import dataclass

import httpx
import instructor
from instructor.core.exceptions import InstructorRetryException
from openai.types.chat import ChatCompletion
from tenacity import AsyncRetrying, stop_after_attempt

from smartmed.model_client import (
    GenerationTimeout,
    InvalidGeneration,
    ModelBusy,
    ModelUnavailable,
    OllamaExtractor,
)
from smartmed.outpatient_prompt import PROMPT_VERSION, SYSTEM_PROMPT
from smartmed.schemas.outpatient import (
    OutpatientDocument,
    OutpatientRequest,
    validate_document,
)


def outpatient_schema(schema: dict, request: OutpatientRequest) -> dict:
    import copy

    result = copy.deepcopy(schema)
    alternatives = []
    for turn in request.turns:
        spans = list(
            dict.fromkeys([turn.text, *re.findall(r"[^，。！？；\n]+[，。！？；]?", turn.text)])
        )
        alternatives.append(
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["turn_id", "quote"],
                "properties": {
                    "turn_id": {"type": "integer", "const": turn.turn_id},
                    "quote": {"type": "string", "enum": spans},
                },
            }
        )
    result["$defs"]["Evidence"] = {"anyOf": alternatives}
    # Keep shared definitions constrained too for introspection and older consumers.
    result["$defs"]["ClinicalItem"]["properties"]["origin"] = {
        "type": "string",
        "const": "transcript",
    }
    result["$defs"]["Section"]["properties"]["reviewed"] = {
        "type": "boolean",
        "const": False,
    }
    return result


@dataclass
class OutpatientExtractionResult:
    document: OutpatientDocument
    metadata: dict


def remove_exact_misplaced_duplicates(payload: dict) -> tuple[dict, list[dict]]:
    """Remove only exact doctor duplicates already preserved in their proper section."""
    import copy

    from smartmed.schemas.outpatient import DOCTOR_SECTIONS, HISTORY_SECTIONS

    result = copy.deepcopy(payload)
    changes = []
    for name in HISTORY_SECTIONS:
        section = result.get(name, {})
        if section.get("status") != "documented":
            continue
        kept = []
        for item in section.get("items", []):
            destination = next(
                (key for key in DOCTOR_SECTIONS if item in result.get(key, {}).get("items", [])),
                None,
            )
            if item.get("reported_by") == "doctor" and destination:
                changes.append({"removed_from": name, "preserved_in": destination})
            else:
                kept.append(item)
        section["items"] = kept
        if not kept:
            section["status"] = "unknown"
    return result, changes


class OutpatientExtractor(OllamaExtractor):
    def __init__(self, settings, transport=None):
        super().__init__(settings, transport)
        self.http.timeout = httpx.Timeout(settings.outpatient_timeout_s)

    async def assign_speakers(self, text: str):
        from smartmed.speaker_assignment import assign_speakers

        return await assign_speakers(self, text)

    async def extract(self, request: OutpatientRequest):
        import asyncio

        if self.lock.locked():
            raise ModelBusy
        async with self.lock:
            try:
                async with asyncio.timeout(
                    self.settings.outpatient_timeout_s * (self.settings.repair_attempts + 1)
                ):
                    return await self._extract(request)
            except TimeoutError as exc:
                raise GenerationTimeout from exc

    async def _extract(self, request: OutpatientRequest) -> OutpatientExtractionResult:
        health = await self.health()
        if not health["ollama_available"] or not health["model_installed"]:
            raise ModelUnavailable
        from smartmed import outpatient_compact as compact

        use_spans = self.settings.outpatient_format != "full"
        response_model = compact.GroupedDocument if use_spans else OutpatientDocument
        system_prompt = compact.SYSTEM_PROMPT if use_spans else SYSTEM_PROMPT
        prompt_version = compact.PROMPT_VERSION if use_spans else PROMPT_VERSION
        attempts = []
        normalizations = []
        started = time.monotonic()
        stage = "extraction"

        async def native_completion(**kwargs) -> ChatCompletion:
            # Instructor prepares schema/retry feedback. Translate its in-memory
            # OpenAI-shaped request to Ollama's native API to enforce think:false.
            schema = kwargs["response_format"]["json_schema"]["schema"]
            if not use_spans:
                schema = outpatient_schema(schema, request)
            else:
                schema = compact.grounded_schema(schema, request)
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
                    "num_thread": self.settings.cpu_threads,
                    "num_ctx": self.settings.context_tokens,
                    "num_predict": 4096,
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
            try:
                parsed, corrections = (
                    (json.loads(content), [])
                    if use_spans
                    else remove_exact_misplaced_duplicates(json.loads(content))
                )
                if corrections:
                    content = json.dumps(parsed, ensure_ascii=False)
                    normalizations.extend(corrections)
            except (ValueError, TypeError, AttributeError):
                pass  # Instructor rejects malformed output; never repair fabricated citations.
            if raw.get("prompt_eval_count", 0) >= self.settings.context_tokens:
                raise InvalidGeneration
            attempts.append(
                {
                    "stage": stage,
                    "done_reason": raw.get("done_reason"),
                    "prompt_tokens": raw.get("prompt_eval_count"),
                    "output_tokens": raw.get("eval_count"),
                    "total_duration_ns": raw.get("total_duration"),
                    "load_duration_ns": raw.get("load_duration"),
                    "prompt_eval_duration_ns": raw.get("prompt_eval_duration"),
                    "eval_duration_ns": raw.get("eval_duration"),
                }
            )
            return ChatCompletion(
                id="local-ollama",
                object="chat.completion",
                created=int(time.time()),
                model=self.settings.model,
                choices=[
                    {
                        "index": 0,
                        "finish_reason": "length" if raw.get("done_reason") == "length" else "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ],
            )

        create = instructor.patch(create=native_completion, mode=instructor.Mode.JSON_SCHEMA)
        try:
            document = await create(
                response_model=response_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"spans": compact.spans(request)}
                            if use_spans
                            else {"turns": [turn.model_dump() for turn in request.turns]},
                            ensure_ascii=False,
                        ),
                    },
                ],
                context={"turns": request.turns, "generated": True, "request": request},
                max_retries=AsyncRetrying(
                    stop=stop_after_attempt(self.settings.repair_attempts + 1),
                    reraise=True,
                ),
                strict=True,
            )
            # Repeat grounding explicitly at the trust boundary, even if a future
            # Instructor release changes how validation context is propagated.
            document = (
                compact.expand(document.model_dump(), request)
                if use_spans
                else validate_document(document.model_dump(), request.turns, generated=True)
            )
            if use_spans and self.settings.outpatient_plan_audit:
                stage = "plan_check"
                plan = await create(
                    response_model=compact.PlanSelection,
                    messages=[
                        {"role": "system", "content": compact.PLAN_PROMPT},
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "spans": [
                                        span
                                        for span in compact.spans(request)
                                        if span["speaker"] == "doctor"
                                    ]
                                },
                                ensure_ascii=False,
                            ),
                        },
                    ],
                    context={"request": request},
                    max_retries=AsyncRetrying(
                        stop=stop_after_attempt(self.settings.repair_attempts + 1),
                        reraise=True,
                    ),
                    strict=True,
                )
                payload = document.model_dump()
                payload["plan"] = compact.merge_plan(
                    document.plan, compact.expand(plan.model_dump(), request).plan
                ).model_dump()
                document = validate_document(payload, request.turns, generated=True)
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
        return OutpatientExtractionResult(
            document=document,
            metadata={
                "model": self.settings.model,
                "digest": health["digest"],
                "prompt_version": prompt_version,
                "generation_format": self.settings.outpatient_format,
                "plan_audit": use_spans and self.settings.outpatient_plan_audit,
                "plan_prompt_sha256": hashlib.sha256(compact.PLAN_PROMPT.encode()).hexdigest()
                if use_spans and self.settings.outpatient_plan_audit
                else None,
                "prompt_sha256": hashlib.sha256(system_prompt.encode()).hexdigest(),
                "think": False,
                "context_tokens": self.settings.context_tokens,
                "output_tokens": 4096,
                "temperature": 0,
                "seed": 42,
                "attempts": attempts,
                "exact_duplicate_normalizations": normalizations,
                "elapsed_s": round(time.monotonic() - started, 3),
            },
        )
