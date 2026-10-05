from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from .soap import EncounterRecord

RefTemplate = "#/$defs/{model}"


def strict_json_schema(require_all: bool = True) -> dict[str, Any]:
    raw = deepcopy(EncounterRecord.model_json_schema(ref_template=RefTemplate))
    defs = raw.pop("$defs", {})
    schema = _dereference(raw, defs, 0)
    return _force_strict(schema, require_all)


def grammar_text() -> str:
    import json

    return json.dumps(strict_json_schema(), ensure_ascii=False, sort_keys=True)


def validate_payload(payload: Any) -> tuple[EncounterRecord | None, list[str]]:
    try:
        return EncounterRecord.model_validate(payload), []
    except ValidationError as exc:
        return None, [
            f"{format_path(error['loc'])}: {error['msg']}"
            for error in exc.errors(include_url=False, include_context=False)
        ]


def format_path(loc: tuple[Any, ...] | list[Any]) -> str:
    text = ""
    for part in loc:
        if isinstance(part, int):
            text = f"{text}[{part}]"
        elif text:
            text = f"{text}.{part}"
        else:
            text = str(part)
    return text or "<root>"


def repair_instructions(errors: list[str], limit: int = 12) -> str:
    if not errors:
        return ""
    lines = [f"- {error}" for error in errors[:limit]]
    if len(errors) > limit:
        lines.append(f"- ({len(errors) - limit} further errors omitted)")
    return "\n".join(lines)


def _dereference(node: Any, defs: dict[str, Any], depth: int) -> Any:
    if depth > 40:
        raise RecursionError("unresolved reference cycle in schema")
    if isinstance(node, list):
        return [_dereference(item, defs, depth + 1) for item in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str):
        name = ref.rsplit("/", 1)[-1]
        if name not in defs:
            raise KeyError(f"missing schema definition {name}")
        base = _dereference(deepcopy(defs[name]), defs, depth + 1)
        siblings = {
            key: _dereference(value, defs, depth + 1)
            for key, value in node.items()
            if key != "$ref"
        }
        if isinstance(base, dict):
            base.update(siblings)
            return base
        return siblings or base
    return {key: _dereference(value, defs, depth + 1) for key, value in node.items()}


def _force_strict(node: Any, require_all: bool) -> Any:
    if isinstance(node, list):
        return [_force_strict(item, require_all) for item in node]
    if not isinstance(node, dict):
        return node
    out = {key: _force_strict(value, require_all) for key, value in node.items()}
    if "properties" in out:
        out["additionalProperties"] = False
        if require_all:
            out["required"] = sorted(out["properties"])
        out.setdefault("required", [])
    return out
