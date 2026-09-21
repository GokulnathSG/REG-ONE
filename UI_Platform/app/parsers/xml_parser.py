from app.parsers.tree_utils import xml_file_to_tree, XmlParseError
from app.parsers.tree_parser import parse_tree, TreeParseError


def parse_xml_file(path: str, source_file: str = ""):
    try:
        root = xml_file_to_tree(path)
    except XmlParseError:
        raise
    try:
        return parse_tree(root, source_file=source_file)
    except TreeParseError as e:
        raise XmlParseError(str(e)) from e
