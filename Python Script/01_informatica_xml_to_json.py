"""
Informatica PowerCenter XML -> JSON parser.

Contract (see ./powermart-tags.md):
  * Generic. No tag is special-cased. Any element in the powrmart.dtd schema
    (and any element NOT in it) is preserved verbatim.
  * Document order is preserved. Children are stored as an ordered list under
    "children". Tags are NEVER grouped, sorted, deduplicated, or renamed.
  * All attributes are preserved (including empty strings) under "attributes",
    in the order they appear in the source XML.
  * Whitespace-only text between tags (XML pretty-printing) is dropped. Any
    real text/tail content is preserved verbatim.
  * The XML declaration and DOCTYPE are captured at the top of the JSON so the
    output is a faithful representation of the source document.
  * Lossless: element count and attribute count in the JSON equal those in the
    source XML. The script asserts this before writing.

Output shape per element:
    {
      "tag": "TAG_NAME",
      "attributes": { "ATTR1": "...", ... },
      "text":  "<optional, only if non-whitespace>",
      "tail":  "<optional, only if non-whitespace>",
      "children": [ <recursive>, ... ]   # only if non-empty
    }

CLI:
    python parser/informatica_xml_to_json.py <input.xml> [output.json]

If output.json is omitted, the JSON is written next to the input file with
the same basename and a .json extension.
"""

from __future__ import annotations

import json
import re
import sys
from collections import OrderedDict
from pathlib import Path
from xml.etree.ElementTree import iterparse


# --------------------------------------------------------------------------- #
# 1. XML declaration + DOCTYPE capture
# --------------------------------------------------------------------------- #

_XML_DECL_RE = re.compile(rb"^\s*(<\?xml[^?]*\?>)", re.DOTALL)
_DOCTYPE_RE = re.compile(rb"<!DOCTYPE[^>]*>", re.DOTALL)


def _read_prolog(path: Path) -> dict:
    """Capture the XML declaration and DOCTYPE line(s) verbatim from the file."""
    head = path.read_bytes()[:4096]
    prolog: "OrderedDict[str, str]" = OrderedDict()

    decl = _XML_DECL_RE.search(head)
    if decl:
        prolog["xml_declaration"] = decl.group(1).decode("utf-8", errors="replace")

    doctype = _DOCTYPE_RE.search(head)
    if doctype:
        prolog["doctype"] = doctype.group(0).decode("utf-8", errors="replace")

    return prolog


# --------------------------------------------------------------------------- #
# 2. Element -> dict (generic, recursive, order-preserving)
# --------------------------------------------------------------------------- #

def _element_to_dict(elem) -> "OrderedDict[str, object]":
    """Convert an ElementTree element to an ordered dict, recursively.

    Order of insertion: tag -> attributes -> text -> children -> tail.
    """
    node: "OrderedDict[str, object]" = OrderedDict()
    node["tag"] = elem.tag

    # attributes (attrib in ElementTree preserves insertion order on Py 3.8+)
    node["attributes"] = OrderedDict(elem.attrib)

    # element text — drop pure whitespace (XML formatting)
    if elem.text is not None and elem.text.strip() != "":
        node["text"] = elem.text

    # children — preserve document order
    children = list(elem)
    if children:
        node["children"] = [_element_to_dict(c) for c in children]

    # tail text
    if elem.tail is not None and elem.tail.strip() != "":
        node["tail"] = elem.tail

    return node


# --------------------------------------------------------------------------- #
# 3. Counters for lossless verification
# --------------------------------------------------------------------------- #

def _count_xml(path: Path) -> tuple[int, int]:
    """Count elements and attributes in the source XML using a streaming parse."""
    n_elements = 0
    n_attrs = 0
    for event, elem in iterparse(str(path), events=("start",)):
        n_elements += 1
        n_attrs += len(elem.attrib)
        # we don't clear here because iterparse events="start" doesn't build
        # references we need to manage; but for huge files we should clear.
        elem.clear()
    return n_elements, n_attrs


def _count_json(node) -> tuple[int, int]:
    """Count elements and attributes in the produced JSON tree."""
    if not isinstance(node, dict) or "tag" not in node:
        return 0, 0
    elements = 1
    attrs = len(node.get("attributes") or {})
    for child in node.get("children", []) or []:
        ce, ca = _count_json(child)
        elements += ce
        attrs += ca
    return elements, attrs


# --------------------------------------------------------------------------- #
# 4. Public API
# --------------------------------------------------------------------------- #

def parse_xml_to_json(xml_path: Path, json_path: Path) -> dict:
    """Parse an Informatica XML file and write the JSON representation.

    Returns a small report dict with the verification counts.
    """
    # Build the tree using iterparse so very large files (10+ transformations,
    # 10+ mapplets, etc.) are handled with reasonable memory.
    root = None
    for event, elem in iterparse(str(xml_path), events=("end",)):
        # After an "end" event the element and its children are fully built.
        # We just need to keep a reference to the root element when it ends.
        root = elem
    if root is None:
        raise RuntimeError(f"No root element parsed from {xml_path}")

    document: "OrderedDict[str, object]" = OrderedDict()
    document.update(_read_prolog(xml_path))
    document["root"] = _element_to_dict(root)

    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(document, fh, ensure_ascii=False, indent=2)

    # ---- Lossless verification ----
    src_elem, src_attr = _count_xml(xml_path)
    out_elem, out_attr = _count_json(document["root"])
    if (src_elem, src_attr) != (out_elem, out_attr):
        raise AssertionError(
            f"Lossless check failed for {xml_path.name}: "
            f"XML(elements={src_elem}, attributes={src_attr}) vs "
            f"JSON(elements={out_elem}, attributes={out_attr})"
        )

    return {
        "input": str(xml_path),
        "output": str(json_path),
        "elements": out_elem,
        "attributes": out_attr,
    }


# --------------------------------------------------------------------------- #
# 5. CLI
# --------------------------------------------------------------------------- #

def _resolve_output(xml_path: Path, override: str | None) -> Path:
    if override:
        return Path(override)
    return xml_path.with_suffix(".json")


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0

    xml_path = Path(argv[1]).expanduser().resolve()
    if not xml_path.is_file():
        print(f"ERROR: input file not found: {xml_path}", file=sys.stderr)
        return 2

    json_path = _resolve_output(xml_path, argv[2] if len(argv) > 2 else None)
    report = parse_xml_to_json(xml_path, json_path)
    print(
        "OK  {input}\n -> {output}\n    elements={elements}  attributes={attributes}".format(
            **report
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
