"""Bound model context without silently dropping transcript content."""

import re

from smartmed.schemas.extraction import (
    FIELDS,
    Extraction,
    ExtractRequest,
    Turn,
    validate_extraction,
)

SEGMENT_CHARS = 1800


def segments(request: ExtractRequest) -> list[ExtractRequest]:
    batches = []
    current = []
    size = 0
    for turn in request.turns:
        # Split only at sentence boundaries. A single oversized sentence is rejected.
        parts = re.findall(r"[^。！？\n]+[。！？\n]?|[。！？\n]", turn.text)
        if any(len(part) > SEGMENT_CHARS for part in parts):
            raise ValueError("single_utterance_too_long")
        fragments = []
        fragment = ""
        for part in parts:
            if len(fragment) + len(part) > SEGMENT_CHARS:
                fragments.append(fragment)
                fragment = ""
            fragment += part
        if fragment:
            fragments.append(fragment)
        for fragment in fragments:
            # Repeated turn IDs belong to separate segments, never the same request.
            if current and (
                size + len(fragment) > SEGMENT_CHARS
                or any(t.turn_id == turn.turn_id for t in current)
            ):
                batches.append(ExtractRequest(turns=current))
                current, size = [], 0
            current.append(Turn(turn_id=turn.turn_id, speaker=turn.speaker, text=fragment))
            size += len(fragment)
    if current:
        batches.append(ExtractRequest(turns=current))
    return batches


def merge(documents: list[Extraction], turns: list[Turn]) -> tuple[Extraction, list[str]]:
    payload = {}
    conflicts = []
    for name in FIELDS:
        facts = [getattr(d, name) for d in documents if getattr(d, name).status != "unknown"]
        identities = {(f.status, f.value) for f in facts}
        if not facts or len(identities) > 1:
            payload[name] = {"status": "unknown", "value": None, "evidence": []}
            if len(identities) > 1:
                conflicts.append(name)
        else:
            # unknown never overwrites a grounded fact. Identical facts combine citations.
            fact = facts[0].model_dump()
            seen = set()
            evidence = []
            for item in facts:
                for e in item.evidence:
                    key = (e.turn_id, e.quote)
                    if key not in seen:
                        evidence.append(e.model_dump())
                        seen.add(key)
            fact["evidence"] = evidence[:8]
            payload[name] = fact
    return validate_extraction(payload, turns), conflicts
