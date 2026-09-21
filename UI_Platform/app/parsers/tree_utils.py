"""Converts a PowerCenter XML export into the same generic
{"tag": ..., "attributes": {...}, "children": [...]} tree shape used by the
JSON input format, so a single tree-walking parser (tree_parser.py) can
handle both. This is what keeps XMLParser and JSONParser format-agnostic
past this point in the pipeline.
"""
from lxml import etree


class XmlParseError(Exception):
    pass


def xml_file_to_tree(path: str) -> dict:
    try:
        parser = etree.XMLParser(resolve_entities=False, no_network=True, dtd_validation=False, load_dtd=False)
        tree = etree.parse(path, parser=parser)
        root = tree.getroot()
    except etree.XMLSyntaxError as e:
        raise XmlParseError(f"Invalid XML: {e.msg} at line {e.lineno}, column {e.offset}") from e
    return _element_to_dict(root)


def _element_to_dict(el) -> dict:
    node = {
        "tag": el.tag,
        "attributes": dict(el.attrib),
        "children": [_element_to_dict(c) for c in el if isinstance(c.tag, str)],
    }
    return node
