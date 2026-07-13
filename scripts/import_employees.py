from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.schemas.employee_database import EmployeeDatabaseUpsertRequest  # noqa: E402
from backend.schemas.profile import EmployeeProfile  # noqa: E402
from backend.services.employee_database_service import EmployeeDatabaseService  # noqa: E402

NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
NS_PACKAGE_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

DATE_HEADERS = {
    "Labor Contract Termination Date",
    "Start Date in Bosch",
    "Position Since",
}

EMPLOYEE_HEADERS = [
    "Personal No.",
    "Name",
    "Legal Entity",
    "GB",
    "Department",
    "Job Grade",
    "Position",
    "HRBP",
    "Leadership Flag",
    "Target Manager",
    "Diciplinary Manager",
    "Labor Contract Termination Date",
    "Start Date in Bosch",
    "Gender",
    "Age",
    "Position Since",
    "Function by Person",
    "历史博世工作经历",
    "Goal",
    "Talent Pool",
    "TCL (SLx)",
    "Performance Rating (A Group)",
    "History ASR Rating",
]


def clean_cell(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def split_list(value: str | None) -> list[str]:
    text = clean_cell(value)
    if not text:
        return []
    return [item.strip() for item in re.split(r"[\n;；]+", text) if item.strip()]


def normalize_date_cell(header: str, value: str) -> str:
    if header not in DATE_HEADERS or not value:
        return value
    if re.fullmatch(r"\d+(?:\.0)?", value):
        days = int(float(value))
        try:
            return (datetime(1899, 12, 30) + timedelta(days=days)).date().isoformat()
        except OverflowError:
            return value
    return value


def normalize_row(row: dict[str, str]) -> dict[str, str]:
    return {header: normalize_date_cell(header, clean_cell(row.get(header))) for header in EMPLOYEE_HEADERS}


def validate_headers(headers: list[str]) -> None:
    missing = [header for header in EMPLOYEE_HEADERS if header not in headers]
    unexpected = [header for header in headers if header and header not in EMPLOYEE_HEADERS]
    if missing or unexpected:
        message_parts = []
        if missing:
            message_parts.append("missing headers: " + ", ".join(missing))
        if unexpected:
            message_parts.append("unexpected headers: " + ", ".join(unexpected))
        raise SystemExit("Employee file headers must match the configured header list exactly; " + "; ".join(message_parts))


def load_rows(path: Path) -> list[dict[str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return load_csv(path)
    if suffix == ".xlsx":
        return load_xlsx(path)
    raise SystemExit(f"Unsupported employee file type: {suffix}. Use .xlsx or .csv")


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers = [clean_cell(header) for header in (reader.fieldnames or [])]
        validate_headers(headers)
        rows: list[dict[str, str]] = []
        for raw in reader:
            row = normalize_row({header: clean_cell(raw.get(header)) for header in headers})
            if any(row.values()):
                rows.append(row)
        return rows


def load_xlsx(path: Path) -> list[dict[str, str]]:
    with zipfile.ZipFile(path) as zf:
        shared = read_shared_strings(zf)
        sheet_path = first_sheet_path(zf)
        sheet = ET.fromstring(zf.read(sheet_path))
        raw_rows: list[dict[int, str]] = []
        for row_node in sheet.findall(f".//{NS_MAIN}sheetData/{NS_MAIN}row"):
            values: dict[int, str] = {}
            for cell in row_node.findall(f"{NS_MAIN}c"):
                ref = cell.attrib.get("r", "")
                col_index = column_index(ref)
                if col_index is None:
                    continue
                value = read_cell(cell, shared)
                values[col_index] = clean_cell(value)
            if any(values.values()):
                raw_rows.append(values)
        if not raw_rows:
            return []
        max_col = max(max(row.keys(), default=0) for row in raw_rows)
        headers = [clean_cell(raw_rows[0].get(idx, "")) for idx in range(max_col + 1)]
        validate_headers(headers)
        rows: list[dict[str, str]] = []
        for raw in raw_rows[1:]:
            row = normalize_row({headers[idx]: clean_cell(raw.get(idx, "")) for idx in range(max_col + 1) if headers[idx]})
            if any(row.values()):
                rows.append(row)
        return rows


def read_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for si in root.findall(f"{NS_MAIN}si"):
        parts = [node.text or "" for node in si.findall(f".//{NS_MAIN}t")]
        strings.append("".join(parts))
    return strings


def first_sheet_path(zf: zipfile.ZipFile) -> str:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    first_sheet = workbook.find(f"{NS_MAIN}sheets/{NS_MAIN}sheet")
    if first_sheet is None:
        raise SystemExit("Workbook has no sheets")
    rid = first_sheet.attrib.get(f"{NS_REL}id")
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    for rel in rels.findall(f"{NS_PACKAGE_REL}Relationship"):
        if rel.attrib.get("Id") == rid:
            target = rel.attrib.get("Target", "")
            target = target.lstrip("/")
            return target if target.startswith("xl/") else f"xl/{target}"
    return "xl/worksheets/sheet1.xml"


def read_cell(cell: ET.Element, shared: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(f".//{NS_MAIN}t"))
    value_node = cell.find(f"{NS_MAIN}v")
    if value_node is None or value_node.text is None:
        return ""
    raw = value_node.text
    if cell_type == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return raw
    return raw


def column_index(ref: str) -> int | None:
    match = re.match(r"([A-Z]+)", ref.upper())
    if not match:
        return None
    total = 0
    for char in match.group(1):
        total = total * 26 + (ord(char) - ord("A") + 1)
    return total - 1


def build_profile(row: dict[str, str]) -> EmployeeProfile:
    return EmployeeProfile(
        employee_alias=row.get("Name") or None,
        role=row.get("Position") or None,
        department=row.get("Department") or None,
        level=row.get("Job Grade") or None,
        reporting_line=row.get("Diciplinary Manager") or row.get("Target Manager") or None,
        performance_rating=row.get("Performance Rating (A Group)") or None,
        key_goals=split_list(row.get("Goal")),
        past_ratings=split_list(row.get("History ASR Rating")),
        historical_feedback=split_list(row.get("历史博世工作经历")),
    )


def build_profile_text(row: dict[str, str]) -> str:
    return "\n".join(f"{header}：{row.get(header, '')}" for header in EMPLOYEE_HEADERS if row.get(header))


def to_payload(row: dict[str, str]) -> EmployeeDatabaseUpsertRequest:
    employee_id = clean_cell(row.get("Personal No."))
    if not employee_id:
        raise ValueError("missing Personal No.")
    profile_text = build_profile_text(row)
    profile = build_profile(row)
    profile.source_profile_text = profile_text
    return EmployeeDatabaseUpsertRequest(
        employee_id=employee_id,
        employee_alias=row.get("Name") or None,
        name=row.get("Name") or None,
        department=row.get("Department") or None,
        role=row.get("Position") or None,
        manager=row.get("Diciplinary Manager") or row.get("Target Manager") or None,
        profile_text=profile_text,
        profile=profile,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Import employee master data from the configured Bosch Excel/CSV headers.")
    parser.add_argument("file", type=Path, help="Path to .xlsx or .csv file")
    parser.add_argument("--dry-run", action="store_true", help="Parse and validate only; do not write database")
    parser.add_argument("--quiet", action="store_true", help="Print compact summary without sample employee records")
    args = parser.parse_args()

    path = args.file
    if not path.exists():
        raise SystemExit(f"File not found: {path}")

    rows = load_rows(path)
    service = None if args.dry_run else EmployeeDatabaseService()
    imported = 0
    errors: list[dict[str, str]] = []
    samples: list[dict[str, object]] = []
    for index, row in enumerate(rows, start=2):
        try:
            payload = to_payload(row)
            if service is not None:
                record = service.upsert(payload)
                if len(samples) < 3:
                    samples.append(record.model_dump(mode="json"))
            else:
                if len(samples) < 3:
                    samples.append(payload.model_dump(mode="json"))
            imported += 1
        except Exception as exc:  # noqa: BLE001
            errors.append({"row": str(index), "error": str(exc)})

    summary = {
        "file": str(path),
        "dry_run": args.dry_run,
        "rows": len(rows),
        "imported": imported,
        "errors": errors,
    }
    if not args.quiet:
        summary["samples"] = samples
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
