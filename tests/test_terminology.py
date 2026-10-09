import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.terminology.app import create_app as create_terminology_app
from services.terminology.build_catalog import build
from services.terminology.catalog import ADDENDUM_SHA256, EXPECTED_ROWS, SOURCE_SHA256, Catalog
from smartmed.api import create_app
from smartmed.backend_settings import BackendSettings

SOURCE = Path("resources/diagnoses/icd10_cn_national_clinical_v2_2019.xlsx")


@pytest.fixture(scope="module")
def catalog(tmp_path_factory):
    path = tmp_path_factory.mktemp("diagnoses") / "catalog.sqlite3"
    assert build(SOURCE, path) == EXPECTED_ROWS
    return Catalog(path)


def test_verified_catalog_searches_exact_names_and_codes(catalog):
    app = create_terminology_app(catalog)
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ready"
        info = client.get("/v1/catalog").json()
        assert info["row_count"] == EXPECTED_ROWS
        assert info["source"]["file_sha256"] == SOURCE_SHA256
        assert info["source"]["addendum_sha256"] == ADDENDUM_SHA256
        assert info["source"]["complete_2022_edition"] is False
        assert info["source"]["current_for_clinical_use"] is False
        result = client.get("/v1/diagnoses/search", params={"q": "急性支气管炎"}).json()
        assert result["matches"][0] == {
            "source_file": SOURCE.name,
            "source_row": 14695,
            "primary_code": "J20.900",
            "additional_code": "",
            "name": "急性支气管炎",
        }
        assert client.get("/v1/diagnoses/lookup", params={"code": "j20.900"}).json()[
            "matches"
        ] == [result["matches"][0]]
        assert client.get("/v1/diagnoses/lookup", params={"code": "B95.000"}).json()[
            "matches"
        ][0]["primary_code"] == ""
        covid = client.get("/v1/diagnoses/lookup", params={"code": "U07.100x002"}).json()
        assert covid["matches"] == [{
            "source_file": "icd10_cn_covid_addendum_2020.csv",
            "source_row": 4,
            "primary_code": "U07.100x002",
            "additional_code": "",
            "name": "新型冠状病毒感染",
        }]


def test_catalog_never_invents_a_code(catalog):
    with TestClient(create_terminology_app(catalog)) as client:
        assert client.get("/v1/diagnoses/search", params={"q": "不存在疾病"}).json()[
            "matches"
        ] == []
        assert client.get("/v1/diagnoses/lookup", params={"code": "ZZZ999"}).status_code == 404
        assert client.get("/v1/diagnoses/search", params={"q": " "}).status_code == 422
        invalid_limit = client.get("/v1/diagnoses/search", params={"q": "J20", "limit": 0})
        assert invalid_limit.status_code == 422


def test_tampered_source_cannot_be_indexed(tmp_path):
    altered = tmp_path / "altered.xlsx"
    altered.write_bytes(SOURCE.read_bytes() + b"x")
    assert hashlib.sha256(altered.read_bytes()).hexdigest() != SOURCE_SHA256
    with pytest.raises(ValueError, match="checksum"):
        build(altered, tmp_path / "catalog.sqlite3")


def test_tampered_addendum_cannot_be_indexed(tmp_path):
    altered = tmp_path / "altered.csv"
    original = Path("resources/diagnoses/icd10_cn_covid_addendum_2020.csv")
    altered.write_bytes(original.read_bytes() + b"x")
    with pytest.raises(ValueError, match="addendum checksum"):
        build(SOURCE, tmp_path / "catalog.sqlite3", altered)


def test_api_exposes_internal_catalog_without_diagnosing(tmp_path, catalog):
    class FakeTerminology:
        async def catalog(self):
            return {"source": {"edition": "test"}, "row_count": catalog.count()}

        async def search(self, query, limit):
            matches, has_more = catalog.search(query, limit)
            return {"source": {"edition": "test"}, "matches": matches, "has_more": has_more}

        async def lookup(self, code):
            return {"source": {"edition": "test"}, "matches": catalog.lookup(code)}

    app = create_app(
        BackendSettings(database=tmp_path / "drafts.sqlite3"),
        terminology_client=FakeTerminology(),
    )
    with TestClient(app) as client:
        response = client.get("/v1/diagnoses/search", params={"q": "J20.900", "limit": 1})
        assert response.status_code == 200
        assert response.json()["matches"][0]["primary_code"] == "J20.900"
        assert response.json()["has_more"] is True
        assert client.get("/v1/diagnoses/catalog").json()["row_count"] == EXPECTED_ROWS
        assert client.get("/v1/diagnoses/search", params={"q": " "}).status_code == 422


def test_terminology_endpoint_cannot_point_to_external_network():
    with pytest.raises(ValidationError):
        BackendSettings(terminology_url="https://codes.example.org")
