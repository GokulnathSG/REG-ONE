import json
from app.parsers.tree_parser import parse_tree, TreeParseError


class JsonParseError(Exception):
    pass


def parse_json_file(path: str, source_file: str = ""):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise JsonParseError(f"Invalid JSON: {e.msg} at line {e.lineno}, column {e.colno}") from e

    root = data.get("root") if isinstance(data, dict) else None
    if root is None:
        raise JsonParseError("JSON input must contain a top-level 'root' element "
                              "(the {tag, attributes, children} export tree).")
    try:
        return parse_tree(root, source_file=source_file)
    except TreeParseError as e:
        raise JsonParseError(str(e)) from e
