import asyncio
import copy
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from smartmed.api import create_app
from smartmed.auth import AuthStore
from smartmed.backend_settings import BackendSettings
from smartmed.outpatient_model import OutpatientExtractor
from smartmed.schemas.extraction import Turn
from smartmed.schemas.outpatient import SECTIONS, OutpatientRequest, validate_document

TURNS = [
    Turn(turn_id=1, speaker="patient", text="我咳嗽两天，还有咽痛。"),
    Turn(turn_id=2, speaker="doctor", text="咽部充血。可能是上呼吸道感染。建议休息。"),
    Turn(turn_id=3, speaker="third_party", text="他昨天咳嗽，我自己对青霉素过敏。"),
]


def empty():
    return {key: {"status": "unknown", "items": [], "reviewed": False} for key in SECTIONS}


def item(text, turn=1, speaker="patient", assertion="present"):
    return {
        "text": text,
        "assertion": assertion,
        "origin": "transcript",
        "reported_by": speaker,
        "evidence": [{"turn_id": turn, "quote": text}],
        "reviewed": False,
    }


def gold():
    result = empty()
    result["chief_complaint"] = {
        "status": "documented",
        "reviewed": False,
        "items": [item("我咳嗽两天"), item("还有咽痛。")],
    }
    result["assessment"] = {
        "status": "documented",
        "reviewed": False,
        "items": [item("可能是上呼吸道感染。", 2, "doctor", "uncertain")],
    }
    result["plan"] = {
        "status": "documented",
        "reviewed": False,
        "items": [item("建议休息。", 2, "doctor")],
    }
    return result


def test_sources_uncertainty_multiple_items_and_unknown():
    doc = validate_document(gold(), TURNS, generated=True)
    assert len(doc.chief_complaint.items) == 2
    assert doc.assessment.items[0].assertion == "uncertain"
    assert doc.allergy_history.status == "unknown"
    assert doc.allergy_history.items == []


@pytest.mark.parametrize(
    "mutation",
    [
        "patient_plan",
        "wrong_role",
        "fake_quote",
        "fake_review",
        "manual_generation",
        "unknown_items",
    ],
)
def test_reject_unsupported_sources_and_model_review(mutation):
    data = gold()
    if mutation == "patient_plan":
        data["plan"]["items"] = [item("我咳嗽两天")]
    elif mutation == "wrong_role":
        data["plan"]["items"][0]["reported_by"] = "patient"
    elif mutation == "fake_quote":
        data["plan"]["items"][0]["evidence"][0]["quote"] = "建议服用阿莫西林。"
    elif mutation == "fake_review":
        data["plan"]["reviewed"] = True
    elif mutation == "manual_generation":
        data["plan"]["items"][0].update(origin="manual", reported_by="clinician", evidence=[])
    else:
        data["plan"]["status"] = "unknown"
    with pytest.raises(ValidationError):
        validate_document(data, TURNS, generated=True)


class LegacyExtractor:
    async def health(self):
        return {"model_installed": True}


class FakeOutpatient:
    async def extract(self, request):
        return SimpleNamespace(
            document=validate_document(gold(), request.turns, generated=True),
            metadata={"fixture": True},
        )


@pytest.fixture
def client(tmp_path):
    settings = BackendSettings(
        database=tmp_path / "drafts.sqlite3", auth_database=tmp_path / "staff.db"
    )
    AuthStore(settings.auth_database).add_staff("reviewer", "test-outpatient-password")
    app = create_app(settings, LegacyExtractor(), outpatient_extractor=FakeOutpatient())
    with TestClient(app) as http:
        yield http


def login(client):
    token = client.post(
        "/v1/auth/login", json={"staff_id": "reviewer", "passcode": "test-outpatient-password"}
    ).json()
    client.headers["Authorization"] = "Bearer " + token["access_token"]


def request():
    return {
        "turns": [t.model_dump() for t in TURNS],
        "transcript_reviewed": True,
        "patient": {"name": "<script>alert(1)</script>"},
        "encounter": {"department": "内科"},
    }


def confirm(client, draft):
    return client.post(
        f"/v1/outpatient/drafts/{draft['id']}/confirm",
        json={
            "expected_version": draft["version"],
            "reviewed": True,
            "reviewed_sections": list(SECTIONS),
            "patient_encounter_reviewed": True,
        },
    )


def test_versioned_review_print_edit_and_audit(client):
    assert client.post("/v1/outpatient/drafts", json=request()).status_code == 401
    login(client)
    unchecked = request()
    unchecked["transcript_reviewed"] = False
    assert client.post("/v1/outpatient/drafts", json=unchecked).status_code == 422
    response = client.post("/v1/outpatient/drafts", json=request())
    assert response.status_code == 201, response.text
    draft = response.json()
    root = "/v1/outpatient/drafts/" + draft["id"]
    assert draft["contract_version"] == "outpatient.v1"
    assert client.get(root + "/export").status_code == 409
    assert client.get(root + "/print").status_code == 409
    assert (
        client.post(
            root + "/confirm",
            json={
                "expected_version": 1,
                "reviewed": True,
                "reviewed_sections": ["plan"] * 9,
                "patient_encounter_reviewed": True,
            },
        ).status_code
        == 422
    )
    checked = confirm(client, draft)
    assert checked.status_code == 200, checked.text
    draft = checked.json()
    assert draft["reviewer"] == "reviewer" and draft["reviewed_at"]
    assert client.get(root + "/export").json()["document"] == draft["document"]
    printed = client.get(root + "/print")
    assert printed.status_code == 200
    assert "<script>alert" not in printed.text
    assert "&lt;script&gt;" in printed.text
    assert "可能是上呼吸道感染" in printed.text
    assert confirm(client, {**draft, "version": 1}).status_code == 409
    data = copy.deepcopy(draft["document"])
    data["plan"]["items"][0].update(
        text="医生补充：一周后复诊。", origin="manual", reported_by="clinician", evidence=[]
    )
    edited = client.put(
        root,
        json={
            "expected_version": draft["version"],
            "document": data,
            "patient": draft["patient"],
            "encounter": draft["encounter"],
        },
    )
    assert edited.status_code == 200, edited.text
    updated = edited.json()
    assert updated["state"] == "requires_review" and updated["reviewer"] is None
    assert updated["reviewed_at"] is None
    assert not updated["document"]["plan"]["items"][0]["reviewed"]
    assert client.get(root + "/export").status_code == 409
    assert confirm(client, updated).status_code == 200
    actions = [r["action"] for r in client.get(root + "/history").json()]
    assert actions == ["generated", "confirmed", "edited", "confirmed"]
    version = client.get(root).json()["version"]
    assert client.delete(root, params={"expected_version": version - 1}).status_code == 409
    assert client.delete(root, params={"expected_version": version}).status_code == 204
    assert client.get(root).status_code == 404


def test_conflict_cannot_be_confirmed(client):
    login(client)
    draft = client.post("/v1/outpatient/drafts", json=request()).json()
    data = draft["document"]
    data["chief_complaint"]["status"] = "conflict"
    draft = client.put(
        "/v1/outpatient/drafts/" + draft["id"],
        json={
            "expected_version": 1,
            "document": data,
            "patient": draft["patient"],
            "encounter": draft["encounter"],
        },
    ).json()
    assert confirm(client, draft).status_code == 409


def test_native_instructor_schema_and_no_patient_metadata():
    seen = []

    def transport(http_request):
        if http_request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "qwen3.5:4b", "digest": "fixture"}]}
            )
        import json

        payload = json.loads(http_request.content)
        seen.append(payload)
        assert set(payload["format"]["properties"]) == set(SECTIONS)
        assert (
            payload["format"]["$defs"]["ClinicalItem"]["properties"]["origin"]["const"]
            == "transcript"
        )
        assert payload["format"]["$defs"]["Section"]["properties"]["reviewed"]["const"] is False
        assert "Secret patient name" not in json.dumps(payload["messages"])
        return httpx.Response(
            200,
            json={"done": True, "done_reason": "stop", "message": {"content": json.dumps(gold())}},
        )

    async def run():
        extractor = OutpatientExtractor(
            BackendSettings(outpatient_format="full"), transport=httpx.MockTransport(transport)
        )
        try:
            req = OutpatientRequest(**{**request(), "patient": {"name": "Secret patient name"}})
            result = await extractor.extract(req)
            assert len(result.document.chief_complaint.items) == 2
            assert result.metadata["prompt_version"] == "outpatient.zh.v4"
        finally:
            await extractor.close()

    asyncio.run(run())
    assert len(seen) == 1


@pytest.mark.parametrize("case", ["doctor_history", "definite_guess", "doctor_question"])
def test_reject_wrong_section_and_tentative_diagnosis(case):
    data = gold()
    turns = list(TURNS)
    if case == "doctor_history":
        data["present_illness"] = {
            "status": "documented",
            "reviewed": False,
            "items": [item("建议休息。", 2, "doctor")],
        }
    elif case == "definite_guess":
        data["assessment"]["items"][0]["assertion"] = "present"
    else:
        turns.append(Turn(turn_id=4, speaker="doctor", text="你咽痛吗？"))
        data["physical_examination"] = {
            "status": "documented",
            "reviewed": False,
            "items": [item("你咽痛吗？", 4, "doctor")],
        }
    with pytest.raises(ValidationError):
        validate_document(data, turns, generated=True)


@pytest.mark.parametrize(
    "question",
    [
        "你妈妈对青霉素过敏吗？",
        "对青霉素过敏吗？对阿莫西林过敏吗？",
        "你知道青霉素过敏是什么意思吗？",
    ],
)
def test_legacy_short_allergy_reply_does_not_negate_patient(question):
    from smartmed.schemas.extraction import FIELDS, validate_extraction

    data = {name: {"status": "unknown", "value": None, "evidence": []} for name in FIELDS}
    data["青霉素过敏"] = {
        "status": "negated",
        "value": None,
        "evidence": [{"turn_id": 2, "quote": "不过敏"}],
    }
    turns = [
        Turn(turn_id=1, speaker="doctor", text=question),
        Turn(turn_id=2, speaker="patient", text="不过敏。"),
    ]
    with pytest.raises(ValidationError):
        validate_extraction(data, turns)


def test_normalization_only_removes_exact_duplicate_without_losing_source():
    from smartmed.outpatient_model import remove_exact_misplaced_duplicates

    data = gold()
    data["present_illness"] = copy.deepcopy(data["plan"])
    cleaned, changes = remove_exact_misplaced_duplicates(data)
    assert cleaned["present_illness"]["status"] == "unknown"
    assert cleaned["plan"] == data["plan"]
    assert changes == [{"removed_from": "present_illness", "preserved_in": "plan"}]
    validate_document(cleaned, TURNS, generated=True)
    data["present_illness"]["items"][0]["text"] = "休息。"
    preserved, changes = remove_exact_misplaced_duplicates(data)
    assert changes == []
    with pytest.raises(ValidationError):
        validate_document(preserved, TURNS, generated=True)
