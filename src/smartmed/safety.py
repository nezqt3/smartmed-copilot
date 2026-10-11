"""Versioned review alerts over extracted facts; never auto-prescribe or alter them."""

from smartmed.medications import AMOXICILLIN_LABEL, INDEX_VERSION, mentions
from smartmed.schemas.extraction import Extraction

RULESET_VERSION = "safety.v1"


def report(document: Extraction, metadata: dict | None = None) -> dict:
    metadata = metadata or {}
    alerts = []

    def add(code, field, message, required=False, source=None):
        alerts.append(
            {
                "code": code,
                "field": field,
                "message": message,
                "requires_acknowledgement": required,
                "source_url": source,
            }
        )

    if document.青霉素过敏.status == "unknown":
        add("allergy_unknown", "青霉素过敏", "青霉素过敏未知，不等于不过敏")
    medication = document.已用药物
    dosage = document.已用药物剂量
    matches = mentions(medication.value) if medication.status == "present" else []
    if medication.status == "present":
        if not matches:
            add("medication_not_indexed", "已用药物", "药物不在演示索引中，需要人工核对", True)
        if dosage.status != "present":
            add("dose_unknown", "已用药物剂量", "已用药物的实际剂量未知，不推断常用剂量")
        if document.青霉素过敏.status != "negated" and any(
            m["family"] == "penicillin" for m in matches
        ):
            add(
                "penicillin_review",
                "已用药物",
                "记录了青霉素类药物且青霉素过敏未明确排除，请人工复核已用药及过敏信息",
                True,
                AMOXICILLIN_LABEL,
            )
    if dosage.status == "present" and medication.status != "present":
        add("dose_without_medication", "已用药物剂量", "剂量存在但没有明确药物，需要人工核对", True)
    for field in metadata.get("merge_conflicts", []):
        add(
            "segment_conflict:" + field,
            field,
            "不同分段输出存在冲突，请核对全文并确认当前记录",
            True,
        )
    return {
        "ruleset_version": RULESET_VERSION,
        "index_version": INDEX_VERSION,
        "alerts": alerts,
        "medications": matches,
        "required_acknowledgements": [a["code"] for a in alerts if a["requires_acknowledgement"]],
    }
