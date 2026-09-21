"""Generate Informatica XML Downloads workbook from a local XML or JSON file.

Usage:
  python informatica_xml_downloads_from_file.py --input wf_CBR_AIM06_XONE.json
  python informatica_xml_downloads_from_file.py --input wf.xml --output out.xlsx
"""
from __future__ import annotations

import argparse
from pathlib import Path

from app.analyzer.workflow_analyzer import compute_execution_order
from app.generators.informatica_xml_downloads_generator import generate_informatica_xml_downloads_excel
from app.parsers.json_parser import parse_json_file
from app.parsers.xml_parser import parse_xml_file


def _parse_input(path: Path):
    ext = path.suffix.lower()
    if ext == ".json":
        return parse_json_file(str(path), source_file=path.name)
    if ext == ".xml":
        return parse_xml_file(str(path), source_file=path.name)
    raise ValueError("Only .json and .xml files are supported.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Informatica XML Downloads workbook from XML/JSON.")
    parser.add_argument("--input", required=True, help="Path to Informatica export file (.json or .xml)")
    parser.add_argument("--output", default="", help="Output .xlsx path (optional)")
    args = parser.parse_args()

    in_path = Path(args.input).expanduser().resolve()
    if not in_path.exists():
        raise FileNotFoundError(f"Input file not found: {in_path}")

    repo = _parse_input(in_path)
    if repo.workflow is None:
        raise ValueError("No <WORKFLOW> element found in the input export.")

    compute_execution_order(repo)

    if args.output:
        out_path = Path(args.output).expanduser().resolve()
    else:
        stem = in_path.stem or "workflow"
        out_path = in_path.parent / f"{stem}_Informatica_XML_Downloads.xlsx"

    output = generate_informatica_xml_downloads_excel(repo, str(out_path))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
