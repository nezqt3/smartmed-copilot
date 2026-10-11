"""Explicit forward-only contract migrations. Never guess a historical schema."""

from collections.abc import Callable

from smartmed.schemas.extraction import CONTRACT_VERSION


def v1_to_v2(payload: dict) -> dict:
    # Existing two-speaker turns remain valid. Do not infer new clinical facts.
    return {**payload, "contract_version": "extraction.v2", "acknowledged_alerts": []}


MIGRATIONS: dict[str, Callable[[dict], dict]] = {"extraction.v1": v1_to_v2}


def migrate(payload: dict) -> dict:
    seen = set()
    while payload.get("contract_version") != CONTRACT_VERSION:
        version = payload.get("contract_version")
        if version in seen or version not in MIGRATIONS:
            raise ValueError(f"Unsupported stored contract version: {version!r}")
        seen.add(version)
        payload = MIGRATIONS[version](payload)
    return payload
