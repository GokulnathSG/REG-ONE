"""Format-agnostic parser: walks the generic {tag, attributes, children} tree
(produced either directly from JSON input, or from XML via tree_utils) and
builds the domain model defined in app/models/domain.py.

This is the single place that knows about PowerCenter's XML/JSON element
names (SOURCE, TARGET, MAPPING, MAPPLET, TRANSFORMATION, WORKFLOW, ...), so
xml_parser.py and json_parser.py are both thin wrappers around parse_tree().
"""
from typing import Dict, Iterator, Optional, List

from app.models.domain import (
    Field, Table, Transformation, Connector, Instance, Mapplet, Mapping,
    Session, WorkflowLink, TaskInstance, Workflow, RepositoryModel,
)


class TreeParseError(Exception):
    pass


def _children(node: dict) -> List[dict]:
    return node.get("children") or []


def _attr(node: dict, name: str, default: str = "") -> str:
    return (node.get("attributes") or {}).get(name, default)


def _direct(node: dict, tag: str) -> List[dict]:
    return [c for c in _children(node) if c.get("tag") == tag]


def _find_all(node: dict, tag: str) -> Iterator[dict]:
    """Recursive descendant search (depth is shallow for PowerCenter exports,
    so plain recursion is fine even for large workflows)."""
    for c in _children(node):
        if c.get("tag") == tag:
            yield c
        yield from _find_all(c, tag)


# ---------------------------------------------------------------- tables ---

def _parse_table(node: dict, kind: str) -> Table:
    field_tag = "SOURCEFIELD" if kind == "SOURCE" else "TARGETFIELD"
    fields = []
    for f in _direct(node, field_tag):
        fields.append(Field(
            name=_attr(f, "NAME"),
            datatype=_attr(f, "DATATYPE"),
            precision=_attr(f, "PRECISION") or _attr(f, "LENGTH"),
            scale=_attr(f, "SCALE"),
        ))
    return Table(
        name=_attr(node, "NAME"),
        kind=kind,
        connection=_attr(node, "DBDNAME"),
        database=_attr(node, "DATABASETYPE"),
        schema=_attr(node, "OWNERNAME"),
        fields=fields,
    )


# --------------------------------------------------------- transformation --

_PASSTHROUGH_TYPES = {"INPUT/OUTPUT"}


def _business_logic_for(ttype: str, attributes: Dict[str, str], expressions: List[dict]) -> str:
    """Heuristic, deterministic business-logic summary derived purely from
    structural metadata already present in the export (no LLM inference)."""
    if ttype == "Filter":
        cond = attributes.get("Filter Condition", "").strip()
        return f"Filters rows where: {cond}" if cond else "Filters rows (condition not set)."
    if ttype == "Router":
        return "Routes rows to multiple output groups based on group filter conditions."
    if ttype == "Lookup Procedure":
        table = attributes.get("Lookup table name", "").strip()
        cond = attributes.get("Lookup Condition", "").strip()
        base = f"Looks up against '{table}'." if table else "Performs a lookup."
        return f"{base} Condition: {cond}" if cond else base
    if ttype == "Aggregator":
        return "Aggregates input rows (see group-by ports and expressions below)."
    if ttype == "Expression" and expressions:
        return f"Derives {len(expressions)} output port(s) via expressions."
    if ttype == "Source Qualifier":
        return "Reads source rows and applies any source-level filter/join override."
    if ttype in ("Joiner",):
        cond = attributes.get("Join Condition", "").strip()
        return f"Joins two pipelines on: {cond}" if cond else "Joins two pipelines."
    if ttype in ("Sequence Generator",):
        return "Generates a sequence of numeric values for downstream ports."
    if ttype in ("Update Strategy",):
        return "Flags rows for insert/update/delete/reject based on its update expression."
    return ""


def _parse_transformation(node: dict, mapping_name: str, mapplet_name: Optional[str] = None) -> Transformation:
    ttype = _attr(node, "TYPE")
    input_ports, output_ports, variable_ports, expressions = [], [], [], []
    for tf in _direct(node, "TRANSFORMFIELD"):
        pname = _attr(tf, "NAME")
        ptype = _attr(tf, "PORTTYPE")
        fld = Field(name=pname, datatype=_attr(tf, "DATATYPE"),
                    precision=_attr(tf, "PRECISION"), scale=_attr(tf, "SCALE"), port_type=ptype)
        if "INPUT" in ptype:
            input_ports.append(fld)
        if "OUTPUT" in ptype:
            output_ports.append(fld)
        if ptype == "VARIABLE":
            variable_ports.append(fld)
        expr = _attr(tf, "EXPRESSION")
        if expr:
            expressions.append({"port": pname, "expression": expr})

    attributes = {}
    for ta in _direct(node, "TABLEATTRIBUTE"):
        name = _attr(ta, "NAME")
        value = _attr(ta, "VALUE")
        if name:
            attributes[name] = value

    business_logic = _business_logic_for(ttype, attributes, expressions)
    impl_notes = "; ".join(f"{k}={v}" for k, v in attributes.items() if v) or "No non-default attributes set."

    return Transformation(
        name=_attr(node, "NAME"),
        type=ttype,
        reusable=_attr(node, "REUSABLE") == "YES",
        input_ports=input_ports, output_ports=output_ports, variable_ports=variable_ports,
        expressions=expressions, attributes=attributes,
        business_logic=business_logic, implementation_notes=impl_notes,
        mapping_name=mapping_name, mapplet_name=mapplet_name,
    )


def _parse_instances(node: dict) -> List[Instance]:
    out = []
    for inst in _direct(node, "INSTANCE"):
        out.append(Instance(
            name=_attr(inst, "NAME"), type=_attr(inst, "TYPE"),
            ref_name=_attr(inst, "TRANSFORMATION_NAME"), ref_type=_attr(inst, "TRANSFORMATION_TYPE"),
        ))
    return out


def _parse_connectors(node: dict) -> List[Connector]:
    out = []
    for c in _direct(node, "CONNECTOR"):
        out.append(Connector(
            from_instance=_attr(c, "FROMINSTANCE"), from_field=_attr(c, "FROMFIELD"),
            to_instance=_attr(c, "TOINSTANCE"), to_field=_attr(c, "TOFIELD"),
        ))
    return out


def _parse_mapping(node: dict, repo: RepositoryModel) -> Mapping:
    name = _attr(node, "NAME")
    instances = _parse_instances(node)
    connectors = _parse_connectors(node)
    transformation_names = []
    for t in _direct(node, "TRANSFORMATION"):
        tobj = _parse_transformation(t, mapping_name=name)
        repo.transformations[f"{name}::{tobj.name}"] = tobj
        transformation_names.append(tobj.name)

    local_names = set(transformation_names)
    for inst in instances:
        if inst.type == "TRANSFORMATION" and inst.ref_name and inst.ref_name not in local_names:
            # References a folder-level reusable transformation (no local copy in this mapping).
            transformation_names.append(inst.ref_name)
            local_names.add(inst.ref_name)

    mapplets = sorted({i.ref_name for i in instances if i.type == "MAPPLET" and i.ref_name})
    sources = sorted({i.ref_name for i in instances if i.type == "SOURCE" and i.ref_name})
    targets = sorted({i.ref_name for i in instances if i.type == "TARGET" and i.ref_name})

    return Mapping(name=name, instances=instances, connectors=connectors,
                    transformations=transformation_names, mapplets=mapplets,
                    sources=sources, targets=targets)


def _parse_mapplet(node: dict, repo: RepositoryModel) -> Mapplet:
    name = _attr(node, "NAME")
    instances = _parse_instances(node)
    connectors = _parse_connectors(node)
    transformation_names = []
    for t in _direct(node, "TRANSFORMATION"):
        tobj = _parse_transformation(t, mapping_name="", mapplet_name=name)
        repo.transformations[f"MAPPLET::{name}::{tobj.name}"] = tobj
        transformation_names.append(tobj.name)
    return Mapplet(name=name, instances=instances, connectors=connectors, transformations=transformation_names)


def _parse_workflow(node: dict) -> Workflow:
    wf = Workflow(name=_attr(node, "NAME"))
    for s in _direct(node, "SESSION"):
        sess = Session(name=_attr(s, "NAME"), mapping_name=_attr(s, "MAPPINGNAME"),
                        reusable=_attr(s, "REUSABLE") == "YES")
        wf.sessions[sess.name] = sess
    for ti in _direct(node, "TASKINSTANCE"):
        wf.task_instances.append(TaskInstance(
            name=_attr(ti, "NAME"), task_name=_attr(ti, "TASKNAME"), task_type=_attr(ti, "TASKTYPE"),
        ))
    for wl in _direct(node, "WORKFLOWLINK"):
        wf.links.append(WorkflowLink(
            from_task=_attr(wl, "FROMTASK"), to_task=_attr(wl, "TOTASK"), condition=_attr(wl, "CONDITION"),
        ))
    return wf


# ------------------------------------------------------------------ entry --

def parse_tree(root: dict, source_file: str = "") -> RepositoryModel:
    if not isinstance(root, dict) or "tag" not in root:
        raise TreeParseError("Root element is not a recognizable PowerCenter export.")

    repo = RepositoryModel()
    folders = list(_find_all(root, "FOLDER"))
    if not folders and root.get("tag") == "FOLDER":
        folders = [root]
    if not folders:
        raise TreeParseError("No <FOLDER> element found in the export.")

    for folder in folders:
        for s in _direct(folder, "SOURCE"):
            t = _parse_table(s, "SOURCE")
            repo.sources[t.name] = t
        for t_ in _direct(folder, "TARGET"):
            t = _parse_table(t_, "TARGET")
            repo.targets[t.name] = t
        for rt in _direct(folder, "TRANSFORMATION"):
            # Folder-level (reusable) transformation, not owned by any single mapping.
            tobj = _parse_transformation(rt, mapping_name="")
            repo.reusable_transformations[tobj.name] = tobj
        for mplt in _direct(folder, "MAPPLET"):
            m = _parse_mapplet(mplt, repo)
            repo.mapplets[m.name] = m
        for mp in _direct(folder, "MAPPING"):
            m = _parse_mapping(mp, repo)
            repo.mappings[m.name] = m
        wf_nodes = _direct(folder, "WORKFLOW")
        if wf_nodes:
            wf = _parse_workflow(wf_nodes[0])
            wf.source_file = source_file
            repo.workflow = wf
            if len(wf_nodes) > 1:
                repo.warnings.append(f"Multiple <WORKFLOW> elements found; only '{wf.name}' was loaded.")

    if repo.workflow is None:
        repo.warnings.append("No <WORKFLOW> element found in the export; Table View/graph will be empty.")

    # Structural validation warnings (non-fatal)
    if repo.workflow:
        for sess in repo.workflow.sessions.values():
            if sess.mapping_name and sess.mapping_name not in repo.mappings:
                repo.warnings.append(
                    f"Session '{sess.name}' references mapping '{sess.mapping_name}' which was not found in this export.")
        for mp in repo.mappings.values():
            for mplt_name in mp.mapplets:
                if mplt_name not in repo.mapplets:
                    repo.warnings.append(
                        f"Mapping '{mp.name}' references mapplet '{mplt_name}' which was not found in this export.")

    return repo
