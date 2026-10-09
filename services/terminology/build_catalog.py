"""Verify the government XLSX and build a deterministic, local SQLite index."""

import csv
import hashlib
import os
import re
import sqlite3
import sys
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from services.terminology.catalog import (
    ADDENDUM_SHA256,
    EXPECTED_BASE_ROWS,
    EXPECTED_ROWS,
    SOURCE_SHA256,
    normalize,
)

NAMESPACE = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
SOURCE_FILE = Path("resources/diagnoses/icd10_cn_national_clinical_v2_2019.xlsx")
DEFAULT_DB = Path("data/diagnoses.sqlite3")
ADDENDUM_FILE = Path("resources/diagnoses/icd10_cn_covid_addendum_2020.csv")


def rows_from_xlsx(path: Path):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != SOURCE_SHA256:
        raise ValueError("Diagnosis source checksum differs from the verified publication")
    with ZipFile(path) as workbook:
        strings_xml = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
        strings = [
            "".join(part.text or "" for part in item.findall(".//x:t", NAMESPACE))
            for item in strings_xml.findall("x:si", NAMESPACE)
        ]
        sheet = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
        for row in sheet.findall(".//x:sheetData/x:row", NAMESPACE):
            values = {}
            for cell in row.findall("x:c", NAMESPACE):
                address = cell.attrib["r"]
                column = re.match(r"[A-Z]+", address).group()
                value = cell.find("x:v", NAMESPACE)
                if value is None:
                    values[column] = ""
                elif cell.attrib.get("t") == "s":
                    values[column] = strings[int(value.text)]
                else:
                    values[column] = value.text or ""
            number = int(row.attrib["r"])
            if number == 3 and [values.get(key) for key in "ABC"] != [
                "主要编码", "附加编码", "疾病名称"
            ]:
                raise ValueError("Unexpected diagnosis source columns")
            if number < 4:
                continue
            primary = values.get("A", "").strip()
            additional = values.get("B", "").strip()
            name = values.get("C", "").strip()
            if not name or not (primary or additional):
                raise ValueError(f"Incomplete diagnosis source row {number}")
            yield number, primary, additional, name


def rows_from_addendum(path: Path):
    if hashlib.sha256(path.read_bytes()).hexdigest() != ADDENDUM_SHA256:
        raise ValueError("Diagnosis addendum checksum differs from the verified transcription")
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["primary_code", "additional_code", "name"]:
            raise ValueError("Unexpected diagnosis addendum columns")
        for number, row in enumerate(reader, start=2):
            primary, additional, name = (row[key].strip() for key in reader.fieldnames)
            if not primary or not name:
                raise ValueError(f"Incomplete diagnosis addendum row {number}")
            yield number, primary, additional, name


def build(source: Path, destination: Path, addendum: Path = ADDENDUM_FILE) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    try:
        with sqlite3.connect(temporary) as db:
            db.executescript(
                """
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE diagnoses (
                    source_file TEXT NOT NULL,
                    source_row INTEGER NOT NULL,
                    primary_code TEXT NOT NULL,
                    additional_code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    primary_key TEXT NOT NULL,
                    additional_key TEXT NOT NULL,
                    name_key TEXT NOT NULL,
                    PRIMARY KEY (source_file, source_row)
                );
                CREATE UNIQUE INDEX diagnoses_primary_code
                    ON diagnoses(primary_key) WHERE primary_key != '';
                CREATE INDEX diagnoses_additional_code ON diagnoses(additional_key);
                """
            )
            count = 0
            for filename, rows in (
                (source.name, rows_from_xlsx(source)),
                (addendum.name, rows_from_addendum(addendum)),
            ):
                for number, primary, additional, name in rows:
                    db.execute(
                        "INSERT INTO diagnoses VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (filename, number, primary, additional, name,
                         normalize(primary), normalize(additional), normalize(name)),
                    )
                    count += 1
            if count != EXPECTED_ROWS:
                raise ValueError(f"Expected {EXPECTED_ROWS} source rows, found {count}")
            base_count = db.execute(
                "SELECT count(*) FROM diagnoses WHERE source_file = ?", (source.name,)
            ).fetchone()[0]
            if base_count != EXPECTED_BASE_ROWS:
                raise ValueError(f"Expected {EXPECTED_BASE_ROWS} base rows, found {base_count}")
            db.execute(
                "INSERT INTO metadata VALUES ('source_sha256', ?)", (SOURCE_SHA256,)
            )
            db.execute(
                "INSERT INTO metadata VALUES ('addendum_sha256', ?)", (ADDENDUM_SHA256,)
            )
        os.replace(temporary, destination)
        return count
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    source_path = Path(sys.argv[1]) if len(sys.argv) > 1 else SOURCE_FILE
    db_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_DB
    addendum_path = Path(sys.argv[3]) if len(sys.argv) > 3 else ADDENDUM_FILE
    count = build(source_path, db_path, addendum_path)
    print(f"Indexed {count} verified diagnosis rows in {db_path}")
