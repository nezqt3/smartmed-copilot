"""Small offline ingredient index. No prescribing doses or inferred substitutions."""

import re

INDEX_VERSION = "medications.2026-10-06"
ATC_BASE = "https://atcddd.fhi.no/atc_ddd_index/?code="
AMOXICILLIN_LABEL = (
    "https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=42f935ca-45ba-4b3e-8b40-9b2d4eb56281"
)


def entry(identifier, zh, en, aliases, atc, family):
    return {
        "id": identifier,
        "name_zh": zh,
        "ingredient": en,
        "aliases": aliases,
        "atc": atc,
        "family": family,
        "source_url": ATC_BASE + atc + "&showdescription=no",
        "verified_on": "2026-10-06",
    }


MEDICATIONS = [
    entry(
        "amoxicillin",
        "阿莫西林",
        "amoxicillin",
        ["阿莫西林", "amoxicillin"],
        "J01CA04",
        "penicillin",
    ),
    entry(
        "benzylpenicillin",
        "苄青霉素",
        "benzylpenicillin",
        ["苄青霉素", "青霉素G", "benzylpenicillin", "penicillin g"],
        "J01CE01",
        "penicillin",
    ),
    entry("ibuprofen", "布洛芬", "ibuprofen", ["布洛芬", "ibuprofen"], "M01AE01", "other"),
    entry(
        "paracetamol",
        "对乙酰氨基酚",
        "paracetamol",
        ["对乙酰氨基酚", "扑热息痛", "paracetamol", "acetaminophen"],
        "N02BE01",
        "other",
    ),
    entry(
        "cefalexin",
        "头孢氨苄",
        "cefalexin",
        ["头孢氨苄", "cefalexin", "cephalexin"],
        "J01DB01",
        "cephalosporin",
    ),
]


def mentions(text: str) -> list[dict]:
    found = []
    for medication in MEDICATIONS:
        for alias in medication["aliases"]:
            pattern = re.escape(alias)
            if alias.isascii():
                pattern = r"(?<![a-z])" + pattern + r"(?![a-z])"
            if re.search(pattern, text, re.IGNORECASE):
                found.append(medication)
                break
    return found


def search(query: str) -> list[dict]:
    query = query.strip().casefold()
    return [
        m
        for m in MEDICATIONS
        if not query or any(query in alias.casefold() for alias in (*m["aliases"], m["atc"]))
    ]
