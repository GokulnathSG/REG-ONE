"""
informatica_lineage_md.py
=========================
Converts Informatica PowerCenter JSON (from xml_to_JSON.py) into a
structured Markdown field-level specification document.

Output sections per target field
---------------------------------
1. Source Table & Field
   Primary Source(s): <table>.<field>  (or <SeqGen>.<field> if sequence generator)
   Lineage Chain: step-by-step Primary Source → Target Field

2. (skipped – no "decision tree" noise)

3. Intermediate Tables  (only real intermediate nodes, not source/target)

4. Business Rules / Conditions
   Join Conditions    (Joiner)
   Filters            (Filter, Source Qualifier WHERE, Router groups, Update Strategy)
   Additional Conditions  (Lookup condition, Aggregator GROUP BY, Sorter, Rank, etc.)

5. Referential Tables  (Lookup reference tables with field names)

CLI
---
python informatica_lineage_md.py \\
    -j <main.json> \\
    -t <TARGET_TABLE_NAME> \\
    [-o <output.md>] \\
    [--transformation-name <INSTANCE_NAME>]   # disambiguate if same target table appears multiple times
    [--folder <FOLDER_NAME>]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# ════════════════════════════════════════════════════════════════════════════
# SECTION 1 – CONSTANTS
# ════════════════════════════════════════════════════════════════════════════

# Informatica built-in functions / SQL keywords – excluded from expression
# field-reference extraction
_INFA_FUNCTIONS: Set[str] = {
    "IIF","ISNULL","ISNUMBER","ISDATE","ISSPACESONLY","NVL","NVL2","NULLIF",
    "COALESCE","LTRIM","RTRIM","TRIM","UPPER","LOWER","SUBSTR","INSTR","LENGTH",
    "LPAD","RPAD","CONCAT","REPLACE","REVERSE","CHR","ASCII","SOUNDEX",
    "REG_EXTRACT","REG_MATCH","REG_REPLACE","ABS","ROUND","TRUNC","FLOOR",
    "CEIL","MOD","POWER","SQRT","EXP","LOG","SIN","COS","TAN","TO_INTEGER",
    "TO_DECIMAL","TO_CHAR","TO_DATE","TO_BIGINT","TO_FLOAT","CAST","CONVERT",
    "DATE_DIFF","ADD_TO_DATE","GET_DATE_PART","MAKE_DATE","SET_DATE_PART",
    "LAST_DAY","NEXT_DAY","SYSTIMESTAMP","SYSDATE","CURRENT_DATE",
    "CURRENT_TIMESTAMP","SUM","AVG","COUNT","MIN","MAX","FIRST","LAST",
    "MEDIAN","PERCENTILE","STDDEV","VARIANCE","SEQGEN","NEXTVAL","CURRVAL",
    "ERROR","ABORT","AND","OR","NOT","TRUE","FALSE","NULL","DECODE",
    "ROW_NUMBER","RANK","DENSE_RANK","OVER","PARTITION","BY","ORDER",
    "ASC","DESC","SELECT","FROM","WHERE","JOIN","INNER","OUTER","LEFT",
    "RIGHT","FULL","CROSS","ON","GROUP","HAVING","UNION","INTERSECT",
    "MINUS","DISTINCT","AS","IN","LIKE","BETWEEN","EXISTS","CASE",
    "WHEN","THEN","ELSE","END","IS","INTO","SET","DUAL","CONNECT",
    "START","WITH","PRIOR","LEVEL","ROWNUM","ROWID","SYSDATE","SYSTIMESTAMP",
    "METAPHONE","METACODE","SNOWID",
}

# Transformation TYPE strings (exactly as they appear in the JSON)
_TTYPE_SQ          = "Source Qualifier"
_TTYPE_EXP         = "Expression"
_TTYPE_FILTER      = "Filter"
_TTYPE_LOOKUP      = "Lookup Procedure"
_TTYPE_JOINER      = "Joiner"
_TTYPE_AGG         = "Aggregator"
_TTYPE_SORTER      = "Sorter"
_TTYPE_ROUTER      = "Router"
_TTYPE_NORM        = "Normalizer"
_TTYPE_RANK        = "Rank"
_TTYPE_UPD         = "Update Strategy"
_TTYPE_JAVA        = "Java"
_TTYPE_UNION       = "Union"
_TTYPE_SEQ         = "Sequence"
_TTYPE_XML_SQ      = "XML Source Qualifier"
_TTYPE_XML_TGT     = "XML Target Definition"
_TTYPE_SP          = "Stored Procedure"
_TTYPE_CUSTOM      = "Custom Transformation"
_TTYPE_MAPPLET     = "Mapplet"
_TTYPE_TARGET      = "Target Definition"
_TTYPE_SOURCE      = "Source Definition"

# All types that are NEVER a primary physical source
_INTERMEDIATE_TYPES: Set[str] = {
    _TTYPE_SQ, _TTYPE_EXP, _TTYPE_FILTER, _TTYPE_LOOKUP,
    _TTYPE_JOINER, _TTYPE_AGG, _TTYPE_SORTER, _TTYPE_ROUTER,
    _TTYPE_NORM, _TTYPE_RANK, _TTYPE_UPD, _TTYPE_JAVA,
    _TTYPE_UNION, _TTYPE_SEQ, _TTYPE_XML_SQ, _TTYPE_XML_TGT,
    _TTYPE_SP, _TTYPE_CUSTOM, _TTYPE_MAPPLET, _TTYPE_TARGET,
}

# Transformation-instance naming prefixes (used to detect intermediate nodes)
_TRANS_PREFIXES = (
    "SQ_","EXP_","EXPTRANS","LKP_","LOOKUP_",
    "FIL_","FILTRANS","FILTER_",
    "NRM_","NORM_",
    "SEQ_",
    "RTR_","ROUTER_",
    "JNR_","JOINER_",
    "AGG_","AGGREGATOR_",
    "SRT_","SORTER_",
    "RANK_",
    "MPT_","MAPLET_",
    "TRANS_","CUSTOM_","CUST_",
    "SQL_",
    "UPD_","UPDATE_",
    "UNION_",
    "JAVA_",
    "XML_",
    "SP_","SPROC_","PROC_",
)

_TRANS_PREFIX_REGEX = re.compile(
    r"^(SQ|EXP|EXPTRANS|FILTRANS|FIL|NRM|NORM|SEQ|RTR|ROUTER|JNR|JOINER|"
    r"AGG|AGG|SRT|SORTER|RANK|LKP|LOOKUP|UPD|UPDATE|JAVA|UNION|XML|SP|"
    r"SPROC|PROC|MPT|MAPLET|TRANS|CUSTOM|CUST|SQL)[A-Z0-9_]*$",
    re.IGNORECASE,
)


def _is_trans_instance(name: str) -> bool:
    """Return True if the name looks like an Informatica transformation instance."""
    u = (name or "").upper()
    if u.startswith(_TRANS_PREFIXES):
        return True
    return bool(_TRANS_PREFIX_REGEX.match(u))


def _is_intermediate_by_any_means(
    tname: str,
    mm: "MappingModel",
    source_tables: set,
) -> bool:
    """
    Definitive check: return True if *tname* is an intermediate transformation
    (i.e. NOT a physical source) using every available signal in priority order.

    Priority:
      1. Explicit trans_type / TRANSFORMATION_TYPE attribute from INSTANCE node
         (covers custom-named Routers/Java that have no standard prefix)
      2. TYPE attribute on the TRANSFORMATION node
      3. Prefix/regex heuristic (_is_trans_instance)
      4. If the name IS in source_tables → definitely NOT intermediate

    Correctly handles:
      - MY_ROUTER   (type = Router, no RTR_ prefix)          → intermediate
      - JAVA_PROC   (type = Java, prefix matches JAVA_)       → intermediate
      - JAVA1       (type = Java, prefix-regex misses it)     → intermediate via type
      - RTR_X       (prefix match)                            → intermediate
      - CUSTOMERS   (in source_tables, no type)               → NOT intermediate
    """
    if not tname:
        return False

    # If it is a known physical source table – never intermediate
    if tname in source_tables:
        return False

    # --- Signal 1: resolve type through all possible paths ---
    ttype = ""
    # Path A: trans_types dict (built from TRANSFORMATION nodes + instance indirection)
    ttype = mm.trans_types.get(tname, "")
    if not ttype:
        # Path B: INSTANCE metadata – TRANSFORMATION_TYPE attribute
        meta = mm.instances.get(tname, {})
        ttype = meta.get("trans_type") or ""
    if not ttype:
        # Path C: INSTANCE metadata – raw TYPE attribute (e.g. "Target Definition")
        meta = mm.instances.get(tname, {})
        ttype = meta.get("type") or ""
    if not ttype:
        # Path D: TRANSFORMATION node TYPE attribute looked up by trans_name alias
        meta = mm.instances.get(tname, {})
        aliased = meta.get("trans_name") or ""
        if aliased:
            ttype = mm.trans_types.get(aliased, "")

    if ttype:
        return ttype in _INTERMEDIATE_TYPES

    # --- Signal 2: prefix/regex heuristic (no type found in metadata) ---
    return _is_trans_instance(tname)


# ════════════════════════════════════════════════════════════════════════════
# SECTION 2 – JSON NAVIGATION HELPERS
# ════════════════════════════════════════════════════════════════════════════

def _attr(node: Dict, key: str, default: Any = "") -> Any:
    """Get an attribute from a JSON node safely."""
    return node.get("attributes", {}).get(key, default) or default


def _children(node: Dict, tag: Optional[str] = None) -> List[Dict]:
    """Get direct children, optionally filtered by tag."""
    kids = node.get("children", []) or []
    if tag:
        return [c for c in kids if isinstance(c, dict) and c.get("tag") == tag]
    return [c for c in kids if isinstance(c, dict)]


def _find_all(node: Any, tag: str) -> List[Dict]:
    """Recursively find all nodes with given tag."""
    results: List[Dict] = []
    if isinstance(node, dict):
        if node.get("tag") == tag:
            results.append(node)
        for child in node.get("children", []) or []:
            results.extend(_find_all(child, tag))
    elif isinstance(node, list):
        for item in node:
            results.extend(_find_all(item, tag))
    return results


def _find_by_name(node: Dict, tag: str, name: str, direct_only: bool = False) -> Optional[Dict]:
    """Find first node with given tag and NAME attribute."""
    kids = _children(node, tag) if direct_only else _find_all(node, tag)
    for n in kids:
        if _attr(n, "NAME") == name:
            return n
    return None


def _resolve_powermart(data: Dict) -> Dict:
    """Navigate to the POWERMART root node in the JSON document."""
    root = data.get("root")
    if isinstance(root, dict) and root.get("tag") == "POWERMART":
        return root
    if data.get("tag") == "POWERMART":
        return data
    # Walk the whole tree
    found = _find_all(data, "POWERMART")
    return found[0] if found else {}


# ════════════════════════════════════════════════════════════════════════════
# SECTION 3 – DOCUMENT MODEL (what we extract per mapping)
# ════════════════════════════════════════════════════════════════════════════

class MappingModel:
    """
    Immutable snapshot of everything needed from one MAPPING node.
    Built once, reused for every target field.
    """

    def __init__(self, mapping_node: Dict):
        self.node = mapping_node
        self.name: str = _attr(mapping_node, "NAME")

        # ── sources & targets ────────────────────────────────────────────────
        # Populated externally from folder-level SOURCE/TARGET nodes
        self.source_tables:    Set[str]             = set()   # physical table names
        self.target_tables:    Set[str]             = set()   # physical table names

        # ── instance → { type, trans_name } ─────────────────────────────────
        self.instances:  Dict[str, Dict[str, str]]  = {}      # name → metadata

        # ── transformations ──────────────────────────────────────────────────
        # name → full transformation node
        self.trans_nodes: Dict[str, Dict]           = {}
        # name → TYPE string
        self.trans_types: Dict[str, str]            = {}

        # ── connectors as (from_instance, from_field) → list[(to_instance, to_field)]
        # and reverse lookup
        self.conn_forward:  Dict[Tuple[str,str], List[Tuple[str,str]]] = defaultdict(list)
        self.conn_backward: Dict[Tuple[str,str], List[Tuple[str,str]]] = defaultdict(list)

        self._build()

    # ── private builders ─────────────────────────────────────────────────────

    def _build(self) -> None:
        self._build_instances()
        self._build_transformations()
        self._build_connectors()

    def _build_instances(self) -> None:
        for inst in _children(self.node, "INSTANCE"):
            name = _attr(inst, "NAME")
            if not name:
                continue
            self.instances[name] = {
                "type":       _attr(inst, "TYPE"),
                "trans_type": _attr(inst, "TRANSFORMATION_TYPE"),
                "trans_name": _attr(inst, "TRANSFORMATION_NAME") or _attr(inst, "REUSABLE_TRANSFORMATION_NAME"),
            }

    def _build_transformations(self) -> None:
        for tn in _children(self.node, "TRANSFORMATION"):
            name = _attr(tn, "NAME")
            if not name:
                continue
            self.trans_nodes[name] = tn
            self.trans_types[name] = _attr(tn, "TYPE")

        # Also resolve instance → trans_name indirection
        for inst_name, meta in self.instances.items():
            tname = meta.get("trans_name")
            if tname and tname in self.trans_nodes and inst_name not in self.trans_nodes:
                self.trans_nodes[inst_name] = self.trans_nodes[tname]
                self.trans_types[inst_name] = self.trans_types.get(tname, meta.get("trans_type",""))

    # Transformation types known to use multiple INPUT groups, where the
    # group qualifier can appear on the TO side of a connector (TOINSTANCE
    # or TOFIELD) rather than the FROM side. Field-side stripping is only
    # applied when the connector's instance is one of these types, so a
    # normal field name elsewhere (which might happen to contain '.' or ':'
    # for unrelated reasons) is never touched.
    _MULTI_INPUT_GROUP_TYPES: Set[str] = {_TTYPE_UNION, _TTYPE_NORM, _TTYPE_XML_SQ}
    # Transformation types known to use multiple OUTPUT groups, where the
    # group qualifier appears on the FROM side (FROMINSTANCE or FROMFIELD).
    _MULTI_OUTPUT_GROUP_TYPES: Set[str] = {_TTYPE_ROUTER, _TTYPE_XML_SQ}

    _GROUP_SEP_RE = re.compile(r"[.:]")

    @staticmethod
    def _strip_group(value: str) -> str:
        """
        Strip a leading 'GROUP.' / 'GROUP:' qualifier from *value*, e.g.
        "GROUP1.ID" -> "ID". Informatica group names never contain '.' or
        ':' themselves, so a plain maxsplit=1 is safe once we already know
        (via the caller's type check) that this field genuinely belongs to
        a multi-group transformation.
        """
        if not value:
            return value
        parts = MappingModel._GROUP_SEP_RE.split(value, maxsplit=1)
        if len(parts) == 2 and parts[0] and parts[1]:
            return parts[1]
        return value

    def _build_connectors(self) -> None:
        for conn in _children(self.node, "CONNECTOR"):
            fi  = _attr(conn, "FROMINSTANCE")
            ff  = _attr(conn, "FROMFIELD")
            ti  = _attr(conn, "TOINSTANCE")
            tf  = _attr(conn, "TOFIELD")
            if not (fi and ff and ti and tf):
                continue

            # Normalise instance names: a group qualifier on the instance
            # itself means "INSTANCE.GROUP" or "INSTANCE:GROUP" — always
            # safe to strip to the bare instance name, since a real
            # Informatica instance name never legitimately contains '.' or
            # ':' (those are reserved as group separators in connectors).
            fi_base = re.split(r"[.:]", fi, 1)[0]
            ti_base = re.split(r"[.:]", ti, 1)[0]

            # Normalise field names ONLY when the owning instance (on that
            # same side of the connector) is a known multi-group
            # transformation type. This is what fixes Union (multi INPUT
            # group: qualifier can land on TOFIELD, e.g. TOFIELD=
            # "GROUP1.ID") and Normalizer/XML Source Qualifier (multi
            # OUTPUT group: qualifier can land on FROMFIELD) without
            # risking any change to ordinary connectors elsewhere, where a
            # field name is never group-qualified and must be left intact.
            fi_type = self.get_trans_type(fi_base)
            ti_type = self.get_trans_type(ti_base)

            ff_base = ff
            if fi_type in self._MULTI_OUTPUT_GROUP_TYPES:
                ff_base = self._strip_group(ff)

            tf_base = tf
            if ti_type in self._MULTI_INPUT_GROUP_TYPES:
                tf_base = self._strip_group(tf)

            # Use normalised base names in BOTH indexes so the tracer's
            # field-level walk (which always queries with bare instance +
            # bare field) finds the connector regardless of which side
            # originally carried the group qualifier.
            # conn_forward  : (fi_base, ff_base) → [(ti_base, tf_base)]
            # conn_backward : (ti_base, tf_base) → [(fi_base, ff_base)]
            self.conn_forward [(fi_base, ff_base)].append((ti_base, tf_base))
            self.conn_backward[(ti_base, tf_base)].append((fi_base, ff_base))

    # ── lookup helpers ────────────────────────────────────────────────────────

    def get_trans_type(self, instance_name: str) -> str:
        # Path A: direct entry in trans_types (built from TRANSFORMATION nodes
        #         and the instance→trans_name indirection in _build_transformations)
        t = self.trans_types.get(instance_name)
        if t:
            return t
        # Path B: INSTANCE TRANSFORMATION_TYPE attribute
        meta = self.instances.get(instance_name, {})
        t = meta.get("trans_type") or ""
        if t:
            return t
        # Path C: INSTANCE raw TYPE attribute (e.g. "Target Definition")
        t = meta.get("type") or ""
        if t:
            return t
        # Path D: resolve via trans_name alias (reusable transformation pointer)
        aliased = meta.get("trans_name") or ""
        if aliased:
            t = self.trans_types.get(aliased, "")
        return t

    def get_trans_node(self, instance_name: str) -> Optional[Dict]:
        return self.trans_nodes.get(instance_name)

    def resolve_physical_table(self, instance_name: str) -> str:
        """
        Direction-agnostic physical-table resolver.

        Used when an instance could be acting as either a SOURCE or a
        TARGET depending on which session/mapping is looking at it (the
        same physical table is often registered in both source_tables and
        target_tables at folder level). This matters for cross-session
        lookups: a table that is the SOURCE of session_4 must resolve to
        the exact same name under which an earlier, non-adjacent session
        (e.g. session_2, not just session_3) indexed it as a TARGET —
        otherwise the ancestry index lookup misses and the table is
        wrongly reported as a Primary Source.

        Priority:
          1. trans_name, if it matches a known physical table (source OR
             target) for this folder.
          2. instance_name itself, if it matches a known physical table.
          3. trans_name anyway (best effort).
          4. instance_name (final fallback).
        """
        meta = self.instances.get(instance_name, {})
        trans_name = meta.get("trans_name") or ""
        known = self.source_tables | self.target_tables

        if trans_name and trans_name in known:
            return trans_name
        if instance_name in known:
            return instance_name
        if trans_name:
            return trans_name
        return instance_name

    def upstream(self, instance: str, field: str) -> List[Tuple[str, str]]:
        """Return [(from_instance, from_field)] feeding (instance, field)."""
        return self.conn_backward.get((instance, field), [])

    def resolve_target_def(self, instance_name: str) -> str:
        """
        Map a target instance name to its physical definition/table name.

        Priority (most authoritative first):
          1. trans_name (TRANSFORMATION_NAME / REUSABLE_TRANSFORMATION_NAME)
             *if* it is a known physical target table for this folder.
             (Previously this was returned unconditionally, which is wrong
             when trans_name is just an internal/reusable alias that does
             NOT match the folder's actual TARGET node NAME — this caused
             cross-session lookups to miss for non-adjacent / randomly
             ordered sessions, since the ancestry index is keyed by the
             real physical TARGET node name.)
          2. instance_name itself, if it is a known physical target table.
          3. trans_name anyway (best-effort, e.g. folder-level TARGET list
             wasn't populated for some reason).
          4. instance_name (final fallback, unchanged old behaviour).
        """
        meta = self.instances.get(instance_name, {})
        trans_name = meta.get("trans_name") or ""

        if trans_name and trans_name in self.target_tables:
            return trans_name
        if instance_name in self.target_tables:
            return instance_name
        if trans_name:
            return trans_name
        return instance_name


# ════════════════════════════════════════════════════════════════════════════
# SECTION 4 – FOLDER SCANNER  (builds MappingModels, source/target registries)
# ════════════════════════════════════════════════════════════════════════════

class FolderScanner:

    def __init__(self, folder_node: Dict):
        self.folder = folder_node

        # Physical source/target table registries
        self.source_fields: Dict[str, str] = {}   # "TABLE.FIELD" → table_name
        self.target_fields: Dict[str, str] = {}   # "TABLE.FIELD" → table_name
        self.source_tables: Set[str] = set()
        self.target_tables: Set[str] = set()

        # All mappings in this folder
        self.mappings: List[MappingModel] = []

        # mapping_name → execution rank (lower = runs earlier).
        # Built from WORKFLOW > TASKINSTANCE(type SESSION) nodes, which
        # reference SESSION objects, which in turn reference a MAPPINGNAME.
        # If no workflow/session info exists in the JSON, this stays empty
        # and ancestry lookups fall back to "ambiguous" reporting instead of
        # silently guessing.
        self.session_order: Dict[str, int] = {}   # mapping_name → rank
        self.session_name_for_mapping: Dict[str, str] = {}  # mapping_name → session NAME

        self._scan()

    def _scan(self) -> None:
        # Source definitions (folder-level SOURCE nodes)
        for src in _children(self.folder, "SOURCE"):
            tname = _attr(src, "NAME")
            if not tname:
                continue
            self.source_tables.add(tname)
            for sf in _children(src, "SOURCEFIELD"):
                fn = _attr(sf, "NAME")
                if fn:
                    self.source_fields[f"{tname}.{fn}"] = tname

        # Target definitions (folder-level TARGET nodes)
        for tgt in _children(self.folder, "TARGET"):
            tname = _attr(tgt, "NAME")
            if not tname:
                continue
            self.target_tables.add(tname)
            for tf in _children(tgt, "TARGETFIELD"):
                fn = _attr(tf, "NAME")
                if fn:
                    self.target_fields[f"{tname}.{fn}"] = tname

        # Mappings
        for mnode in _children(self.folder, "MAPPING"):
            model = MappingModel(mnode)
            model.source_tables = self.source_tables
            model.target_tables = self.target_tables
            self.mappings.append(model)

        # Workflow / session execution order (best-effort; absent in some exports)
        self._scan_workflow_order()

    def _scan_workflow_order(self) -> None:
        """
        Parse WORKFLOW → SESSION → TASKINSTANCE nodes to recover real
        session execution order within the folder.

        Actual nesting (confirmed against a real export):
            WORKFLOW
             ├─ SESSION (NAME=..., MAPPINGNAME=...)        [one per session]
             │   ├─ TASKINSTANCE (NAME=...)                [nested INSIDE Session]
             │   ├─ WORKFLOWVARIABLE
             │   └─ ATTRIBUTE
             ├─ SESSION ...
             └─ WORKFLOWLINK (FROMTASK=..., TOTASK=...)     [siblings of SESSION,
                                                              NOT nested inside it]

        Critically: WORKFLOWLINK's FROMTASK/TOTASK reference the
        TASKINSTANCE's own NAME — NOT the parent SESSION's NAME. A SESSION
        and its child TASKINSTANCE can have different NAME values, so the
        two must be bridged explicitly:

            TaskInstance.NAME  →  (owning) Session  →  Session.MAPPINGNAME

        The previous version of this method keyed session_to_mapping by
        SESSION.NAME directly and then tried to look it up using task names
        pulled from WORKFLOWLINK/TASKINSTANCE — those two key spaces don't
        match in general, so session_order silently ended up empty on real
        exports shaped like this one, even though a WORKFLOW node was
        present. That's the actual reason ordering wasn't being recovered.

        If the JSON has no WORKFLOW node at all (mapping-only export), this
        is a no-op and self.session_order stays empty — callers must treat
        that as "execution order unknown" rather than guessing.
        """
        # Bridge: TaskInstance.NAME -> MAPPINGNAME (via the owning Session).
        # Built by walking each SESSION's own TASKINSTANCE children, so the
        # task-name key space always matches what WORKFLOWLINK uses.
        taskinstance_to_mapping: Dict[str, str] = {}
        # Also keep Session.NAME -> MAPPINGNAME as a fallback bridge, in case
        # a link or fallback ordering ever references the Session name itself
        # instead of its TaskInstance's name (defensive; harmless if unused).
        session_to_mapping: Dict[str, str] = {}

        def _index_session(sess: Dict) -> None:
            sname = _attr(sess, "NAME")
            mname = _attr(sess, "MAPPINGNAME")
            if not mname:
                return
            if sname:
                session_to_mapping[sname] = mname
            # TASKINSTANCE lives inside this SESSION node — search recursively
            # under sess (not under WORKFLOW) so nesting depth doesn't matter.
            for ti in _find_all(sess, "TASKINSTANCE"):
                tiname = _attr(ti, "NAME") or _attr(ti, "TASKINSTANCE")
                if tiname:
                    taskinstance_to_mapping[tiname] = mname

        for wf in _children(self.folder, "WORKFLOW"):
            for sess in _find_all(wf, "SESSION"):
                _index_session(sess)
        # SESSION objects can also live at folder level (reusable sessions)
        for sess in _children(self.folder, "SESSION"):
            _index_session(sess)

        rank = 0
        seen_mappings: Set[str] = set()
        for wf in _children(self.folder, "WORKFLOW"):
            # WORKFLOWLINK gives the true execution sequence via FROMTASK/
            # TOTASK, which are TaskInstance names — siblings of SESSION
            # under WORKFLOW, so _children(wf, ...) is the right scope here.
            ordered_task_names = self._linked_task_order(wf)
            if not ordered_task_names:
                # Fallback: no link graph found — use TASKINSTANCE document
                # order, gathered from inside every SESSION under this
                # workflow (TASKINSTANCE is nested, not a direct WF child).
                ordered_task_names = [
                    _attr(ti, "NAME") or _attr(ti, "TASKINSTANCE")
                    for sess in _find_all(wf, "SESSION")
                    for ti in _find_all(sess, "TASKINSTANCE")
                ]
            for task_name in ordered_task_names:
                if not task_name:
                    continue
                mapping_name = (
                    taskinstance_to_mapping.get(task_name)
                    or session_to_mapping.get(task_name)
                )
                if not mapping_name:
                    continue
                if mapping_name in seen_mappings:
                    continue
                self.session_order[mapping_name] = rank
                self.session_name_for_mapping[mapping_name] = task_name
                seen_mappings.add(mapping_name)
                rank += 1

    def _linked_task_order(self, wf: Dict) -> List[str]:
        """
        Best-effort topological order from WORKFLOWLINK FROMTASK/TOTASK pairs.
        Returns [] if no usable link graph is found (caller falls back to
        document order).
        """
        links = _children(wf, "WORKFLOWLINK")
        if not links:
            return []
        froms: List[str] = []
        edges: Dict[str, List[str]] = defaultdict(list)
        indeg: Dict[str, int] = defaultdict(int)
        nodes: Set[str] = set()
        for link in links:
            f = _attr(link, "FROMTASK")
            t = _attr(link, "TOTASK")
            if not f or not t:
                continue
            nodes.add(f)
            nodes.add(t)
            edges[f].append(t)
            indeg[t] += 1
            froms.append(f)
        if not nodes:
            return []
        # Kahn's algorithm – stable order among ties via original appearance
        order: List[str] = []
        queue = [n for n in nodes if indeg.get(n, 0) == 0]
        # Preserve deterministic order: nodes with indegree 0 in first-seen order
        seen_order = []
        for n in froms:
            if n not in seen_order and indeg.get(n, 0) == 0:
                seen_order.append(n)
        queue = seen_order or queue
        visited: Set[str] = set()
        while queue:
            n = queue.pop(0)
            if n in visited:
                continue
            visited.add(n)
            order.append(n)
            for nxt in edges.get(n, []):
                indeg[nxt] -= 1
                if indeg[nxt] <= 0 and nxt not in visited:
                    queue.append(nxt)
        # Append any nodes the link graph didn't reach (disconnected tasks)
        for n in nodes:
            if n not in visited:
                order.append(n)
        return order

    def get_target_field_list(self, target_table: str) -> List[str]:
        """Return all field names defined for a target table."""
        return [
            key.split(".", 1)[1]
            for key in self.target_fields
            if self.target_fields[key] == target_table
        ]

    # ── Cross-session ancestry index ─────────────────────────────────────────
    # Built lazily on first use.
    # Maps physical_table_name → [MappingModel, ...] for every mapping in this
    # folder where that table appears as a TARGET instance (one-to-MANY,
    # since more than one session can legitimately target the same table
    # name in different mappings/folders).
    # Used by the cross-session tracer to jump backward from "a table that is
    # a source in mapping M" to "the mapping that originally wrote that table
    # as its target", enabling recursive multi-hop, NON-sequential lineage —
    # i.e. session_4's source can resolve directly to session_2 even when
    # session_3 never touches that table at all.

    def _ensure_ancestry_index(self) -> None:
        """Lazily build self._table_written_by: table_name → [MappingModel]."""
        if hasattr(self, "_table_written_by"):
            return
        idx: Dict[str, List["MappingModel"]] = defaultdict(list)
        for mm in self.mappings:
            for inst_name, meta in mm.instances.items():
                itype = (meta.get("type") or meta.get("trans_type") or "").upper()
                if "TARGET" not in itype:
                    continue
                physical = mm.resolve_target_def(inst_name)
                for key in (physical, inst_name):
                    if mm not in idx[key]:
                        idx[key].append(mm)
        self._table_written_by: Dict[str, List["MappingModel"]] = idx

    def find_upstream_mapping(
        self, table_name: str, current_mapping: Optional["MappingModel"] = None
    ) -> Optional["MappingModel"]:
        """
        Return the single best MappingModel whose TARGET instance writes
        *table_name*, or None if no such mapping exists in this folder.

        Disambiguation when MULTIPLE mappings write the same table name
        (the case that breaks on random/dynamic, non-sequential session
        graphs):
          1. If real session execution order is known (self.session_order,
             populated from WORKFLOW/TASKINSTANCE/SESSION nodes) AND
             *current_mapping* is known: pick the candidate with the
             HIGHEST rank that is still STRICTLY EARLIER than
             current_mapping's rank. This is "the most recent session that
             ran before the one asking" — the correct notion of "upstream"
             regardless of whether that session is adjacent or not.
          2. If session order is known but current_mapping's rank is
             unknown, or no candidate qualifies under rule 1: fall back to
             the highest-ranked candidate overall.
          3. If session order is NOT known at all: cannot safely
             disambiguate among multiple candidates. Return the first
             candidate (legacy behaviour) but the ambiguity is recorded in
             self.last_ambiguous_tables for the caller to surface to the
             user — silent wrong answers are worse than a flagged guess.
        """
        self._ensure_ancestry_index()
        candidates = self._table_written_by.get(table_name) or []
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        # Multiple sessions write this table name → needs disambiguation.
        if self.session_order:
            cur_rank = (
                self.session_order.get(current_mapping.name)
                if current_mapping is not None else None
            )
            ranked = [
                (self.session_order.get(c.name), c) for c in candidates
            ]
            if cur_rank is not None:
                earlier = [
                    (r, c) for r, c in ranked
                    if r is not None and r < cur_rank
                ]
                if earlier:
                    earlier.sort(key=lambda rc: rc[0])
                    return earlier[-1][1]   # latest session strictly before current
            # Fall back: highest-ranked known candidate overall
            known = [(r, c) for r, c in ranked if r is not None]
            if known:
                known.sort(key=lambda rc: rc[0])
                return known[-1][1]

        # No usable order info → record ambiguity, return first as best-effort.
        if not hasattr(self, "last_ambiguous_tables"):
            self.last_ambiguous_tables: Dict[str, List[str]] = {}
        self.last_ambiguous_tables[table_name] = [c.name for c in candidates]
        return candidates[0]
        return self._table_written_by.get(table_name)

    def find_mapping_for_target(
        self,
        target_table: str,
        transformation_name: Optional[str] = None,
    ) -> List[Tuple["MappingModel", str]]:
        """
        Return (mapping_model, target_instance_name) pairs that write to target_table.
        If transformation_name is given only that instance is returned (handles
        duplicate target tables in the same mapping – issue-2).
        """
        results: List[Tuple[MappingModel, str]] = []
        for mm in self.mappings:
            for inst_name, meta in mm.instances.items():
                ttype = (meta.get("type") or meta.get("trans_type") or "").upper()
                if "TARGET" not in ttype:
                    continue
                resolved = mm.resolve_target_def(inst_name)
                if resolved != target_table and inst_name != target_table:
                    continue
                if transformation_name and inst_name != transformation_name:
                    continue
                results.append((mm, inst_name))
        return results


# ════════════════════════════════════════════════════════════════════════════
# SECTION 5 – LINEAGE TRACER  (backward connector walk + expression expand)
# ════════════════════════════════════════════════════════════════════════════

class LineageTracer:
    """
    Traces a single target field backward through connectors to its
    physical source(s).

    Returns a list of strings representing ordered lineage steps.
    Steps look like:
      "SRC_TABLE.FIELD_NAME"
      "EXP_TRANS.CALC_FIELD"
      "EXPR:EXP_TRANS.CALC_FIELD = IIF(ISNULL(X), 0, X)"   ← expression annotation
    """

    MAX_DEPTH = 60

    def __init__(self, scanner: FolderScanner):
        self.scanner = scanner
        self._visited: Set[str] = set()

    # ── public entry ──────────────────────────────────────────────────────────

    def trace(
        self,
        field: str,
        instance: str,
        mm: MappingModel,
        depth: int = 0,
    ) -> List[str]:
        """
        Trace *field* in *instance* backward through connectors.

        Cross-session recursion
        -----------------------
        When a step reaches what appears to be a terminal node (no upstream
        connector found) AND that node's table name is itself a TARGET in some
        earlier mapping in this folder, we cross the session boundary:
          1. Find the upstream mapping that writes that table.
          2. Find the target-instance for that table in that mapping.
          3. Recursively trace the same field from that target-instance in
             the upstream mapping.
          4. The steps from the upstream mapping are prepended, giving a
             single continuous chain from the ultimate source to here.

        This loop repeats until either:
          • No upstream mapping exists for the table  (= true physical source), OR
          • The cycle-guard (_visited) fires           (= loop protection).
        """
        if depth > self.MAX_DEPTH:
            return [f"{instance}.{field}"]

        key = f"{mm.name}::{instance}.{field}"
        if key in self._visited:
            return [f"{instance}.{field}"]
        self._visited.add(key)

        # Who feeds (instance, field) within this mapping?
        upstream = mm.upstream(instance, field)

        # Within-mapping cross-mapping fallback (same folder, different MAPPING node)
        if not upstream:
            for other_mm in self.scanner.mappings:
                if other_mm is mm:
                    continue
                up = other_mm.upstream(instance, field)
                if up:
                    upstream = up
                    mm = other_mm
                    break

        if not upstream:
            # ── Cross-session boundary check ──────────────────────────────
            # No connector found inside any mapping for (instance, field).
            # Check whether the *instance* itself (or its resolved physical
            # table name) is also a TARGET in an earlier mapping.
            # If so, recurse into that upstream mapping for the same field.
            physical = mm.resolve_physical_table(instance)
            upstream_mm = (
                self.scanner.find_upstream_mapping(physical, current_mapping=mm)
                or self.scanner.find_upstream_mapping(instance, current_mapping=mm)
            )
            if upstream_mm and upstream_mm is not mm:
                # Find which instance in upstream_mm is the target for physical
                upstream_tgt_inst = self._find_target_instance(upstream_mm, physical, instance)
                if upstream_tgt_inst:
                    cross_key = f"{upstream_mm.name}::{upstream_tgt_inst}.{field}"
                    if cross_key not in self._visited:
                        # Recurse into the upstream session
                        upstream_steps = self.trace(
                            field, upstream_tgt_inst, upstream_mm, depth + 1
                        )
                        # upstream_steps already ends with upstream_tgt_inst.field
                        # Append the current step to complete the chain
                        upstream_steps.append(f"{instance}.{field}")
                        return _dedup(upstream_steps)

            # True terminal: expression-computed field or bare source field
            expr_steps = self._expand_expression(field, instance, mm, depth)
            if expr_steps:
                return expr_steps + [f"{instance}.{field}"]
            return [f"{instance}.{field}"]

        # Recurse upstream for each feeder within this mapping.
        # When there is more than one feeder (a genuine merge point — Union,
        # Joiner, multi-group Normalizer, etc.), wrap each branch's steps in
        # explicit markers so the renderer can present them as clearly
        # labeled "Branch 1 / Branch 2" sub-chains instead of silently
        # flattening parallel pipelines into one misleading linear sequence.
        # Markers contain no '.' character, so every existing chain consumer
        # (_find_primary_sources, _instances_from_chain, _find_intermediates,
        # ConditionExtractor/ReferentialExtractor) safely skips them via
        # their existing "if '.' not in step: skip" guards — no other logic
        # needs to change.
        all_steps: List[str] = []
        multi_branch = len(upstream) > 1
        for branch_idx, (from_inst, from_field) in enumerate(upstream, start=1):
            if multi_branch:
                all_steps.append(f"BRANCH:{instance}:{branch_idx}:START")
            steps = self.trace(from_field, from_inst, mm, depth + 1)
            all_steps.extend(steps)
            # Capture expression annotation if the feeder is an expression trans
            expr_ann = self._get_expression_annotation(from_field, from_inst, mm)
            if expr_ann:
                all_steps.append(expr_ann)
            if multi_branch:
                all_steps.append(f"BRANCH:{instance}:{branch_idx}:END")

        all_steps.append(f"{instance}.{field}")
        return _dedup(all_steps)

    def _find_target_instance(
        self,
        mm: MappingModel,
        physical_table: str,
        fallback_inst: str,
    ) -> Optional[str]:
        """
        Return the name of the TARGET instance in *mm* that resolves to
        *physical_table*.  Falls back to *fallback_inst* if a direct match
        cannot be confirmed (handles cases where instance name == table name).
        """
        for inst_name, meta in mm.instances.items():
            itype = (meta.get("type") or meta.get("trans_type") or "").upper()
            if "TARGET" not in itype:
                continue
            resolved = mm.resolve_target_def(inst_name)
            if resolved == physical_table or inst_name == physical_table:
                return inst_name
        # Fallback: if the instance exists in mm and its type contains TARGET
        if fallback_inst in mm.instances:
            meta = mm.instances[fallback_inst]
            itype = (meta.get("type") or meta.get("trans_type") or "").upper()
            if "TARGET" in itype:
                return fallback_inst
        return None

    # ── expression helpers ────────────────────────────────────────────────────

    def _get_expression_annotation(
        self, field: str, instance: str, mm: MappingModel
    ) -> Optional[str]:
        """
        If the instance is an Expression/Aggregator/etc. transformation AND
        the field has a non-trivial EXPRESSION attribute, return an annotation string.
        """
        ttype = mm.get_trans_type(instance)
        if ttype not in (_TTYPE_EXP, _TTYPE_AGG, _TTYPE_FILTER,
                         _TTYPE_ROUTER, _TTYPE_RANK, _TTYPE_NORM, _TTYPE_UPD):
            return None
        trans_node = mm.get_trans_node(instance)
        if not trans_node:
            return None
        for tf in _children(trans_node, "TRANSFORMFIELD"):
            if _attr(tf, "NAME") != field:
                continue
            expr = _attr(tf, "EXPRESSION")
            if expr and expr.strip() and expr.strip() != field:
                return f"EXPR:{instance}.{field} = {expr.strip()}"
        return None

    def _expand_expression(
        self, field: str, instance: str, mm: MappingModel, depth: int
    ) -> List[str]:
        """
        For a field with no upstream connector, check if it has an EXPRESSION
        that references other fields in the same transformation, and trace those.
        """
        trans_node = mm.get_trans_node(instance)
        if not trans_node:
            return []
        expr = ""
        for tf in _children(trans_node, "TRANSFORMFIELD"):
            if _attr(tf, "NAME") == field:
                expr = _attr(tf, "EXPRESSION")
                break
        if not expr or expr.strip() == field:
            return []

        # Find what fields inside this transformation the expression references
        all_names = {
            _attr(tf, "NAME")
            for tf in _children(trans_node, "TRANSFORMFIELD")
            if _attr(tf, "NAME")
        }
        refs = _extract_field_refs(expr, all_names)
        refs = [r for r in refs if r != field]
        if not refs:
            return [f"EXPR:{instance}.{field} = {expr.strip()}"]

        steps: List[str] = [f"EXPR:{instance}.{field} = {expr.strip()}"]
        for ref in refs:
            steps.extend(self.trace(ref, instance, mm, depth + 1))
        return steps

    def reset(self) -> None:
        self._visited.clear()


# ════════════════════════════════════════════════════════════════════════════
# SECTION 6 – CONDITION EXTRACTOR
# ════════════════════════════════════════════════════════════════════════════

class ConditionExtractor:
    """
    Given a set of transformation instances on the lineage path, extract
    all relevant business rules / conditions from each transformation.
    """

    def __init__(self, mm: MappingModel):
        self.mm = mm

    def extract(self, lineage_instances: Set[str]) -> Dict[str, List[str]]:
        """
        Returns dict with keys:
          "join"       – Joiner join conditions
          "filter"     – Filter / Router / SQ WHERE / Update Strategy
          "additional" – Lookup, Aggregator GROUP BY, Sorter, Rank, Seq, etc.
        """
        result: Dict[str, List[str]] = {"join": [], "filter": [], "additional": []}

        for inst in lineage_instances:
            ttype = self.mm.get_trans_type(inst)
            tnode = self.mm.get_trans_node(inst)
            if not tnode:
                continue

            tas = {
                _attr(ta, "NAME"): _attr(ta, "VALUE")
                for ta in _children(tnode, "TABLEATTRIBUTE")
                if _attr(ta, "NAME")
            }

            # ── Joiner ───────────────────────────────────────────────────────
            if ttype == _TTYPE_JOINER:
                cond = tas.get("Join Condition") or tas.get("Condition") or ""
                if cond:
                    result["join"].append(f"[{inst}] {_compact_cond(cond)}")

            # ── Filter ───────────────────────────────────────────────────────
            elif ttype == _TTYPE_FILTER:
                cond = tas.get("Filter Condition") or ""
                if cond:
                    result["filter"].append(f"[{inst}] {_compact_cond(cond)}")

            # ── Source Qualifier WHERE ────────────────────────────────────────
            elif ttype in (_TTYPE_SQ, _TTYPE_XML_SQ):
                sql = tas.get("Sql Query") or tas.get("User Defined Join") or ""
                where = _extract_where(sql)
                if where:
                    result["filter"].append(f"[{inst}/SQ WHERE] {_compact_cond(where)}")
                user_join = tas.get("User Defined Join") or ""
                if user_join and user_join != sql:
                    result["join"].append(f"[{inst}/SQ User Defined Join] {_compact_cond(user_join)}")

            # ── Router groups ─────────────────────────────────────────────────
            elif ttype == _TTYPE_ROUTER:
                for grp in _children(tnode, "GROUP"):
                    gname = _attr(grp, "NAME")
                    gcond = ""
                    for gta in _children(grp, "TABLEATTRIBUTE"):
                        if _attr(gta, "NAME") in ("Filter Condition", "Condition", "FILTER_CONDITION"):
                            gcond = _attr(gta, "VALUE")
                            break
                    if not gcond:
                        gcond = (_attr(grp, "CONDITION") or _attr(grp, "FILTER_CONDITION")
                                 or _attr(grp, "FILTERCONDITION") or "")
                    if gcond:
                        result["filter"].append(f"[{inst}/Router:{gname}] {_compact_cond(gcond)}")

            # ── Update Strategy ───────────────────────────────────────────────
            elif ttype == _TTYPE_UPD:
                cond = (tas.get("Update Strategy Expression")
                        or tas.get("UpdateStrategy") or "")
                if cond:
                    result["filter"].append(f"[{inst}/UpdateStrategy] {_compact_cond(cond)}")

            # ── Lookup ────────────────────────────────────────────────────────
            elif ttype == _TTYPE_LOOKUP:
                lkp_cond = (tas.get("Lookup condition")
                            or tas.get("Lookup Sql Override") or "")
                if lkp_cond:
                    result["additional"].append(f"[{inst}/Lookup condition] {_compact_cond(lkp_cond)}")

            # ── Aggregator GROUP BY ───────────────────────────────────────────
            if ttype == _TTYPE_AGG:
                grp_flds = [
                    _attr(tf, "NAME")
                    for tf in _children(tnode, "TRANSFORMFIELD")
                    if "GROUP" in (_attr(tf, "PORTTYPE") or "").upper()
                    and _attr(tf, "NAME")
                ]
                if grp_flds:
                    result["additional"].append(
                        f"[{inst}/Aggregator GROUP BY] {', '.join(grp_flds)}"
                    )

            # ── Sorter ────────────────────────────────────────────────────────
            if ttype == _TTYPE_SORTER:
                sort_keys = [
                    f"{_attr(tf,'NAME')} {_attr(tf,'SORTORDER') or _attr(tf,'SORT_DIRECTION') or 'ASC'}"
                    for tf in _children(tnode, "TRANSFORMFIELD")
                    if any(k in (_attr(tf, "PORTTYPE") or "").upper()
                           for k in ("KEY", "SORTKEY", "SORT_KEY"))
                ]
                if sort_keys:
                    result["additional"].append(
                        f"[{inst}/Sorter] Sort by: {', '.join(sort_keys)}"
                    )

            # ── Rank ──────────────────────────────────────────────────────────
            if ttype == _TTYPE_RANK:
                top = tas.get("Top Rows") or tas.get("Toprows") or ""
                rank_keys = [
                    _attr(tf, "NAME")
                    for tf in _children(tnode, "TRANSFORMFIELD")
                    if "KEY" in (_attr(tf, "PORTTYPE") or "").upper()
                    and _attr(tf, "NAME")
                ]
                if top or rank_keys:
                    parts: List[str] = []
                    if top:
                        parts.append(f"Top {top} rows")
                    if rank_keys:
                        parts.append(f"Rank by: {', '.join(rank_keys)}")
                    result["additional"].append(f"[{inst}/Rank] {' | '.join(parts)}")

            # ── Sequence Generator ────────────────────────────────────────────
            if ttype == _TTYPE_SEQ:
                seq_parts: List[str] = []
                for k in ("Start Value", "Increment By", "End Value", "Cycle"):
                    v = tas.get(k) or tas.get(k.replace(" ", "_").upper())
                    if v:
                        seq_parts.append(f"{k}={v}")
                if seq_parts:
                    result["additional"].append(
                        f"[{inst}/Sequence] {', '.join(seq_parts)}"
                    )

            # ── Stored Procedure ──────────────────────────────────────────────
            if ttype == _TTYPE_SP:
                sp_name = (tas.get("Procedure Name") or tas.get("SP Name")
                           or tas.get("Stored Procedure Name") or "")
                if sp_name:
                    result["additional"].append(f"[{inst}/StoredProc] {sp_name}")

            # ── Java ──────────────────────────────────────────────────────────
            if ttype == _TTYPE_JAVA:
                cls = tas.get("Class Name") or tas.get("Java Class Name") or ""
                if cls:
                    result["additional"].append(f"[{inst}/Java] class: {cls}")

        return result


# ════════════════════════════════════════════════════════════════════════════
# SECTION 7 – REFERENTIAL TABLE EXTRACTOR
# ════════════════════════════════════════════════════════════════════════════

class ReferentialExtractor:
    """
    Collects all Lookup reference table names + fields that are on the
    lineage path for a given target field.
    """

    def __init__(self, mm: MappingModel):
        self.mm = mm

    def extract(
        self,
        lineage_instances: Set[str],
        lineage_steps: List[str],
    ) -> List[str]:
        """Returns list of "REF_TABLE.FIELD" strings."""
        results: List[str] = []
        seen: Set[str] = set()

        for inst in lineage_instances:
            ttype = self.mm.get_trans_type(inst)
            if ttype != _TTYPE_LOOKUP:
                continue
            tnode = self.mm.get_trans_node(inst)
            if not tnode:
                continue

            # Get reference table name
            ref_table = ""
            for ta in _children(tnode, "TABLEATTRIBUTE"):
                if _attr(ta, "NAME") == "Lookup table name":
                    ref_table = _normalize_table((_attr(ta, "VALUE") or "").strip())
                    break
            if not ref_table:
                # Fallback: parse from Lookup Sql Override
                for ta in _children(tnode, "TABLEATTRIBUTE"):
                    if _attr(ta, "NAME") == "Lookup Sql Override":
                        tables = _sql_tables(_attr(ta, "VALUE") or "")
                        if tables:
                            ref_table = tables[0]
                        break

            if not ref_table:
                continue

            # Get lookup port fields (LOOKUP porttype = reference table columns)
            for tf in _children(tnode, "TRANSFORMFIELD"):
                ptype = (_attr(tf, "PORTTYPE") or "").upper()
                fname = _attr(tf, "NAME")
                if not fname:
                    continue
                if "LOOKUP" in ptype:
                    key = f"{ref_table}.{fname}"
                    if key not in seen:
                        seen.add(key)
                        results.append(key)

            # Also extract fields from lookup condition
            lkp_cond = ""
            for ta in _children(tnode, "TABLEATTRIBUTE"):
                n = _attr(ta, "NAME")
                if n in ("Lookup condition", "Lookup Sql Override"):
                    lkp_cond = _attr(ta, "VALUE") or ""
                    break
            if lkp_cond:
                for tok in _cond_field_tokens(lkp_cond):
                    key = f"{ref_table}.{tok}"
                    if key not in seen:
                        seen.add(key)
                        results.append(key)

        return results


# ════════════════════════════════════════════════════════════════════════════
# SECTION 8 – FIELD SPEC BUILDER  (orchestrates per-field data collection)
# ════════════════════════════════════════════════════════════════════════════

class FieldSpecBuilder:

    def __init__(self, scanner: FolderScanner):
        self.scanner = scanner

    def build(
        self,
        target_field: str,
        target_table: str,
        mm: MappingModel,
        target_instance: str,
    ) -> Dict[str, Any]:
        """
        Returns a dict:
          target_field     str
          primary_sources  List[str]   "TABLE.FIELD" or "SEQGEN_INST.FIELD (Sequence Generator)"
          lineage_chain    List[str]   ordered steps – from ULTIMATE source to this target
          intermediates    List[str]   transformation nodes between ultimate source and target
          conditions       Dict        {join, filter, additional} – across ALL sessions
          referential      List[str]   REF_TABLE.FIELD – across ALL sessions
          is_seq_gen       bool

        Cross-session behaviour
        -----------------------
        The lineage tracer now recurses backward through session boundaries.
        When a step reaches what looks like a terminal physical source but
        that table is also a TARGET in an earlier mapping in the same folder,
        the trace continues into that upstream mapping automatically.

        After tracing, the raw chain spans ALL sessions end-to-end.
        We then collect conditions and referential tables from EVERY mapping
        that appears on the chain, not just the final (user-specified) one.
        """
        tracer = LineageTracer(self.scanner)
        raw_chain = tracer.trace(target_field, target_instance, mm)

        # Build clean lineage chain (human-readable steps)
        lineage_chain = _build_clean_chain(raw_chain, target_table, target_field)

        # Collect ALL mapping models that contributed to this chain
        # (the tracer may have crossed into upstream mappings)
        all_mms = self._collect_all_mms(raw_chain, mm)

        # Identify ALL intermediate instances across every session
        lineage_instances = _instances_from_chain(raw_chain)

        # Primary source detection – searches the full multi-session chain
        primary_sources = self._find_primary_sources(raw_chain, all_mms, lineage_instances)

        # Is the field driven by a Sequence Generator (any session)?
        is_seq = self._has_sequence_gen_multi(lineage_instances, all_mms)
        if is_seq:
            for inst in lineage_instances:
                for amb in all_mms:
                    if amb.get_trans_type(inst) == _TTYPE_SEQ:
                        primary_sources = [f"{inst}.NEXTVAL (Sequence Generator)"]
                        break

        # Intermediate tables: transformation nodes between ultimate source and target
        intermediates = self._find_intermediates(lineage_chain, target_table, target_field)

        # Conditions – collect from every mapping model on the chain
        conditions: Dict[str, List[str]] = {"join": [], "filter": [], "additional": []}
        for amb in all_mms:
            # Only pass instances that belong to this mapping
            mm_insts = {
                i for i in lineage_instances
                if i in amb.instances or i in amb.trans_types
            }
            cond_ext = ConditionExtractor(amb)
            sub = cond_ext.extract(mm_insts)
            for k in ("join", "filter", "additional"):
                for item in sub[k]:
                    if item not in conditions[k]:
                        conditions[k].append(item)

        # Referential tables – collect from every mapping model on the chain
        referential: List[str] = []
        ref_seen: Set[str] = set()
        for amb in all_mms:
            mm_insts = {
                i for i in lineage_instances
                if i in amb.instances or i in amb.trans_types
            }
            ref_ext = ReferentialExtractor(amb)
            for r in ref_ext.extract(mm_insts, lineage_chain):
                if r not in ref_seen:
                    ref_seen.add(r)
                    referential.append(r)

        return {
            "target_field":    f"{target_table}.{target_field}",
            "primary_sources": primary_sources,
            "lineage_chain":   lineage_chain,
            "intermediates":   intermediates,
            "conditions":      conditions,
            "referential":     referential,
            "is_seq_gen":      is_seq,
        }

    def _collect_all_mms(
        self, raw_chain: List[str], final_mm: MappingModel
    ) -> List[MappingModel]:
        """
        Walk the raw chain and collect every MappingModel whose instances or
        trans_types contain at least one step name from the chain.
        Always includes *final_mm* (the starting mapping).
        Order: upstream mappings first, final mapping last.
        """
        chain_instances = _instances_from_chain(raw_chain)
        seen_names: Set[str] = set()
        result: List[MappingModel] = []

        for amb in self.scanner.mappings:
            if amb.name in seen_names:
                continue
            # This mapping contributed if any chain instance is known to it
            if any(
                i in amb.instances or i in amb.trans_types
                for i in chain_instances
            ):
                seen_names.add(amb.name)
                result.append(amb)

        # Guarantee final_mm is present even if it has no chain instances (edge case)
        if final_mm.name not in seen_names:
            result.append(final_mm)

        return result

    # ── helpers ───────────────────────────────────────────────────────────────

    def _find_primary_sources(
        self,
        raw_chain: List[str],
        all_mms: List[MappingModel],
        lineage_instances: Set[str],
    ) -> List[str]:
        """
        Walk the full multi-session raw chain and collect ultimate physical
        source entries.

        Physical source = a step whose table-prefix:
          • exists in scanner.source_tables, AND
          • is NOT a target table in ANY mapping on the chain, AND
          • is NOT identified as an intermediate transformation by ANY signal
            across ALL mapping models on the chain.

        Cross-session note: a table that is a TARGET in some mapping but a
        SOURCE in the next mapping appears as an intermediate hop in the
        chain.  It must NOT be returned as a primary source.  The check
        `tname in all_target_tables` eliminates those hops so the returned
        source is always the earliest upstream physical table.

        Fallback: if nothing qualifies, pick the very first non-intermediate
        non-target step, still applying the full unified guard.
        """
        scanner = self.scanner

        # Collect target-table names from EVERY mapping on the chain so that
        # staging / intermediate tables are never mistaken for primary sources.
        all_target_tables: Set[str] = set(scanner.target_tables)
        for amb in all_mms:
            for inst_name, meta in amb.instances.items():
                itype = (meta.get("type") or meta.get("trans_type") or "").upper()
                if "TARGET" in itype:
                    all_target_tables.add(amb.resolve_target_def(inst_name))
                    all_target_tables.add(inst_name)

        sources: List[str] = []

        def _is_intermediate_in_any(tname: str) -> bool:
            """True if tname is an intermediate in ANY mapping on the chain."""
            for amb in all_mms:
                if _is_intermediate_by_any_means(tname, amb, scanner.source_tables):
                    return True
            return False

        def _resolves_to_target_in_any(tname: str) -> bool:
            """
            True if tname is a SOURCE-side alias whose resolved physical
            table is itself a target anywhere in the chain — e.g. a local
            "Target_A_SRC2" source instance that really just re-reads
            physical table "Target_A", which an earlier session writes as
            its target. Such aliases must NOT be reported as primary
            sources; they are intermediate hops one resolve-step away from
            a genuine target table.
            """
            for amb in all_mms:
                if tname not in amb.instances:
                    continue
                resolved = amb.resolve_physical_table(tname)
                if resolved != tname and resolved in all_target_tables:
                    return True
            return False

        for step in raw_chain:
            if not isinstance(step, str):
                continue
            if step.startswith("EXPR:"):
                continue
            if step.startswith("BRANCH:"):
                continue
            if "." not in step:
                continue
            tname, _ = step.split(".", 1)
            tname = tname.strip()

            # Skip any table that is a target anywhere in the chain
            if tname in all_target_tables:
                continue

            # Skip source-side aliases that resolve to a target elsewhere
            if _resolves_to_target_in_any(tname):
                continue

            # Skip known intermediates (transformation instances)
            if _is_intermediate_in_any(tname):
                continue

            if step not in sources:
                sources.append(step)

        # ── Fallback: still apply the full multi-session guard ───────────────
        if not sources:
            for step in raw_chain:
                if (
                    not isinstance(step, str)
                    or step.startswith("EXPR:")
                    or step.startswith("BRANCH:")
                    or "." not in step
                ):
                    continue
                tname, _ = step.split(".", 1)
                tname = tname.strip()
                if tname in all_target_tables:
                    continue
                if _resolves_to_target_in_any(tname):
                    continue
                if _is_intermediate_in_any(tname):
                    continue
                if step not in sources:
                    sources.append(step)
                    break

        return sources

    def _has_sequence_gen(self, instances: Set[str], mm: MappingModel) -> bool:
        return any(mm.get_trans_type(i) == _TTYPE_SEQ for i in instances)

    def _has_sequence_gen_multi(self, instances: Set[str], all_mms: List[MappingModel]) -> bool:
        return any(
            amb.get_trans_type(i) == _TTYPE_SEQ
            for i in instances
            for amb in all_mms
        )

    def _find_intermediates(
        self,
        chain: List[str],
        target_table: str,
        target_field: str,
    ) -> List[str]:
        """
        Return all TRANSFORMATION steps between the ultimate source and the
        final target across ALL sessions.

        Rules:
          - Skip the first step (ultimate physical source).
          - Skip the last step (final target table.field).
          - Skip any step whose prefix is a physical source table.
          - Skip any step whose prefix is a target table in ANY mapping
            (these are inter-session staging hops, not transformation nodes).
          - Keep everything else: these are the real intermediate
            transformation nodes (EXP_, SQ_, JNR_, RTR_, etc.).

        EXPR: annotation steps are excluded from intermediates but are kept
        in the full lineage chain for context.
        """
        scanner = self.scanner
        target_key = f"{target_table}.{target_field}"

        # All target table names across all mappings in this folder
        all_target_tables: Set[str] = set(scanner.target_tables)
        scanner._ensure_ancestry_index()
        for tbl in getattr(scanner, "_table_written_by", {}):
            all_target_tables.add(tbl)

        # Steps that are not EXPR annotations and have a "."
        clean = [
            s for s in chain
            if isinstance(s, str)
            and not s.startswith("EXPR:")
            and "." in s
        ]

        if len(clean) <= 2:
            return []

        # Exclude first (ultimate source) and last (final target)
        middle = clean[1:-1]
        results: List[str] = []
        seen: Set[str] = set()
        for step in middle:
            tname = step.split(".", 1)[0].strip()
            # Skip physical source tables
            if tname in scanner.source_tables:
                continue
            # Skip ANY target table (including staging / inter-session hops)
            if tname in all_target_tables:
                continue
            if step == target_key:
                continue
            if step not in seen:
                seen.add(step)
                results.append(step)

        return results


# ════════════════════════════════════════════════════════════════════════════
# SECTION 9 – MARKDOWN RENDERER
# ════════════════════════════════════════════════════════════════════════════

class MarkdownRenderer:

    @staticmethod
    def render(specs: List[Dict[str, Any]], target_table: str) -> str:
        lines: List[str] = []
        lines.append(f"# Field-Level Specification: `{target_table}`\n")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        lines.append("\n---\n")

        for idx, spec in enumerate(specs, 1):
            lines.append(MarkdownRenderer._render_field(spec, idx))
            lines.append("\n---\n")

        return "\n".join(lines)

    @staticmethod
    def _render_field(spec: Dict[str, Any], idx: int) -> str:
        lines: List[str] = []
        tf = spec["target_field"]
        lines.append(f"## Field {idx}: `{tf}`\n")

        # ── Section 1: Source Table & Field ──────────────────────────────────
        lines.append("### 1. Source Table & Field\n")
        srcs = spec["primary_sources"]
        if srcs:
            src_str = ", ".join(f"`{s}`" for s in srcs)
            lines.append(f"**Primary Source(s):** {src_str}\n")
        else:
            lines.append("**Primary Source(s):** *Not identified*\n")

        lines.append("\n**Lineage Chain:**\n")
        chain = spec["lineage_chain"]
        primary_set = set(spec.get("primary_sources") or [])
        if chain:
            rendered = MarkdownRenderer._render_chain_steps(
                chain, primary_set, tf, indent=""
            )
            lines.extend(rendered)
        else:
            lines.append("*(No lineage chain found)*")
        lines.append("\n")

        # ── Section 3: Intermediate Tables ───────────────────────────────────
        intermediates = spec["intermediates"]
        lines.append("### 3. Intermediate Tables\n")
        if intermediates:
            for entry in intermediates:
                lines.append(f"- `{entry}`")
        else:
            lines.append("- *No intermediate tables*")
        lines.append("\n")

        # ── Section 4: Business Rules / Conditions ────────────────────────────
        conds = spec["conditions"]
        has_any_condition = any(conds[k] for k in ("join", "filter", "additional"))
        if has_any_condition:
            lines.append("### 4. Business Rules / Conditions\n")
            if conds["join"]:
                lines.append("**Join Conditions:**\n")
                for c in conds["join"]:
                    lines.append(f"- {c}")
                lines.append("")
            if conds["filter"]:
                lines.append("**Filters:**\n")
                for c in conds["filter"]:
                    lines.append(f"- {c}")
                lines.append("")
            if conds["additional"]:
                lines.append("**Additional Conditions:**\n")
                for c in conds["additional"]:
                    lines.append(f"- {c}")
                lines.append("")
            lines.append("\n")

        # ── Section 5: Referential Tables ─────────────────────────────────────
        referential = spec["referential"]
        if referential:
            lines.append("### 5. Referential Tables\n")
            for r in referential:
                lines.append(f"- `{r}`")
            lines.append("\n")

        return "\n".join(lines)

    _BRANCH_MARKER_RE = re.compile(r"^BRANCH:(.+):(\d+):(START|END)$")

    @staticmethod
    def _render_chain_steps(
        chain: List[str],
        primary_set: Set[str],
        target_field_key: str,
        indent: str,
    ) -> List[str]:
        """
        Render a (possibly marker-annotated) flat chain into Markdown lines,
        recursively grouping BRANCH:<merge_inst>:<n>:START / :END marker
        pairs into clearly labeled "Branch 1 / Branch 2" sub-lists. This is
        what makes Union/Joiner/multi-group merge points readable: each
        incoming pipeline is shown as its own numbered sub-chain instead of
        being flattened into one misleading linear sequence.
        """
        lines: List[str] = []
        i = 0
        step_no = 1
        n = len(chain)
        while i < n:
            step = chain[i]
            m = MarkdownRenderer._BRANCH_MARKER_RE.match(step) if isinstance(step, str) else None
            if m and m.group(3) == "START":
                merge_inst, branch_idx = m.group(1), m.group(2)
                end_marker = f"BRANCH:{merge_inst}:{branch_idx}:END"
                # Find the matching END marker for this exact branch
                j = i + 1
                depth = 1
                while j < n:
                    if chain[j] == step:
                        depth += 1
                    elif chain[j] == end_marker:
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                inner = chain[i + 1: j]
                lines.append(f"{indent}**Branch {branch_idx}** (feeds `{merge_inst}`):")
                sub_lines = MarkdownRenderer._render_chain_steps(
                    inner, primary_set, target_field_key, indent=indent + "    "
                )
                lines.extend(sub_lines)
                i = j + 1  # skip past END marker
                continue
            if m and m.group(3) == "END":
                # Should be consumed by the START handler above; skip defensively.
                i += 1
                continue
            ann = MarkdownRenderer._annotate_step(step, primary_set, target_field_key)
            lines.append(f"{indent}{step_no}. `{step}`{ann}")
            step_no += 1
            i += 1
        return lines

    @staticmethod
    def _annotate_step(step: str, primary_set: Set[str], target_field_key: str) -> str:
        """
        Return a short italicised annotation for a lineage chain step.

        Primary Source / Target are now determined by actual membership
        (step is in the spec's resolved primary_sources, or step equals the
        target field key) rather than positional index — positional index
        stopped being reliable once multi-branch chains can place the true
        ultimate source anywhere within a labeled branch, not necessarily
        at position 0.
        """
        if step.startswith("EXPR:"):
            return "  *(Expression / Derived)*"
        if "." not in step:
            return ""
        tname = step.split(".", 1)[0].strip()
        upper = tname.upper()

        if step == target_field_key:
            return "  *(Target)*"
        if step in primary_set:
            return "  *(Primary Source)*"

        # Type-specific annotations by prefix
        for prefix, label in [
            (("SQ_",), "Source Qualifier"),
            (("JNR_", "JNR", "JOINER_"), "Joiner"),
            (("EXP_", "EXPTRANS"), "Expression"),
            (("FIL_", "FILTRANS", "FILTER_"), "Filter"),
            (("LKP_", "LOOKUP_"), "Lookup"),
            (("RTR_", "ROUTER_"), "Router"),
            (("AGG_", "AGGREGATOR_"), "Aggregator"),
            (("SRT_", "SORTER_"), "Sorter"),
            (("RANK_",), "Rank"),
            (("NRM_", "NORM_"), "Normalizer"),
            (("SEQ_",), "Sequence Generator"),
            (("UPD_", "UPDATE_"), "Update Strategy"),
            (("UNION_",), "Union"),
            (("JAVA_",), "Java"),
            (("MPT_", "MAPLET_"), "Mapplet"),
            (("XML_",), "XML"),
            (("SP_", "SPROC_", "PROC_"), "Stored Procedure"),
        ]:
            if upper.startswith(prefix):
                return f"  *({label}: {tname})*"

        if _is_trans_instance(tname):
            return f"  *(Intermediate: {tname})*"
        return "  *(Intermediate Table)*"


# ════════════════════════════════════════════════════════════════════════════
# SECTION 10 – UTILITY FUNCTIONS
# ════════════════════════════════════════════════════════════════════════════

def _dedup(lst: List[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for item in lst:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _build_clean_chain(
    raw: List[str], target_table: str, target_field: str
) -> List[str]:
    """
    Convert raw tracer output to clean, ordered steps (remove EXPR: prefix
    from chain entries but keep them as inline annotations, collapse dupes).
    EXPR: annotations are kept inline as separate chain steps since they
    carry important context.
    """
    return _dedup(raw)


def _instances_from_chain(chain: List[str]) -> Set[str]:
    """Extract all transformation instance names from a lineage chain."""
    instances: Set[str] = set()
    for step in chain:
        if not isinstance(step, str):
            continue
        if step.startswith("EXPR:"):
            # "EXPR:INST.FIELD = ..."
            body = step[5:]
            if "." in body:
                instances.add(body.split(".", 1)[0].strip())
            continue
        if "." in step:
            instances.add(step.split(".", 1)[0].strip())
    return instances


def _extract_field_refs(expression: str, available: Set[str]) -> List[str]:
    """Extract field references from an Informatica expression."""
    expr = re.sub(r"--.*", " ", expression)
    expr = re.sub(r"'[^']*'", " ", expr)
    tokens = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", expr)
    refs: List[str] = []
    for tok in tokens:
        if tok.upper() in _INFA_FUNCTIONS:
            continue
        if tok in available and tok not in refs:
            refs.append(tok)
    return refs


def _compact_cond(text: str) -> str:
    """Normalise whitespace in a condition string (keep table.field references)."""
    return re.sub(r"\s+", " ", (text or "").strip())


def _extract_where(sql: str) -> str:
    """Extract WHERE clause from a SQL string."""
    sql = re.sub(r"/\*.*?\*/", " ", sql or "", flags=re.DOTALL)
    sql = re.sub(r"--.*", " ", sql)
    sql = re.sub(r"\s+", " ", sql).strip()
    m = re.search(r"\bWHERE\b(.+?)(?:\bGROUP\s+BY\b|\bORDER\s+BY\b|\bHAVING\b|$)",
                  sql, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip().rstrip(";")
    return ""


def _normalize_table(name: str) -> str:
    n = (name or "").strip().strip('`[]"').split("@", 1)[0]
    if "." in n:
        n = n.split(".")[-1]
    return n.strip().strip('`[]"')


def _sql_tables(sql: str) -> List[str]:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--.*", " ", sql)
    sql = re.sub(r"\s+", " ", sql).strip()
    tables: List[str] = []
    for m in re.finditer(r"\b(?:FROM|JOIN)\s+([^\s,()]+)", sql, re.IGNORECASE):
        t = _normalize_table(m.group(1))
        if t and t.upper() not in {
            "SELECT","WHERE","ON","GROUP","ORDER","HAVING","UNION","DUAL"
        } and t not in tables:
            tables.append(t)
    return tables


def _cond_field_tokens(cond: str) -> List[str]:
    """Extract possible field names from a condition string."""
    text = re.sub(r"--.*", " ", cond)
    text = re.sub(r"'[^']*'", " ", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\b", " ", text)
    tokens = re.findall(r"\b[A-Za-z_][A-Za-z0-9_$#\.]*\b", text)
    result: List[str] = []
    for tok in tokens:
        t = tok.strip().strip('`[]"')
        if "." in t:
            t = t.split(".")[-1]
        if t and t.upper() not in _INFA_FUNCTIONS and t not in result:
            result.append(t)
    return result


# ════════════════════════════════════════════════════════════════════════════
# SECTION 11 – ORCHESTRATOR
# ════════════════════════════════════════════════════════════════════════════

class Orchestrator:

    def __init__(self, json_path: str):
        print(f"Loading JSON: {json_path}")
        with open(json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.powermart = _resolve_powermart(data)
        if not self.powermart:
            raise RuntimeError("POWERMART root not found in JSON")

    def run(
        self,
        target_table: str,
        folder_name: Optional[str],
        transformation_name: Optional[str],
        output_path: str,
    ) -> None:

        # ── choose folder ────────────────────────────────────────────────────
        folder_node = self._get_folder(folder_name)
        fn_display = _attr(folder_node, "NAME") or "(first folder)"
        print(f"Folder  : {fn_display}")
        print(f"Target  : {target_table}")
        if transformation_name:
            print(f"Instance: {transformation_name}")

        scanner = FolderScanner(folder_node)

        # ── locate target mappings ───────────────────────────────────────────
        pairs = scanner.find_mapping_for_target(target_table, transformation_name)
        if not pairs:
            raise RuntimeError(
                f"Target table '{target_table}' not found in any mapping instance.\n"
                f"Available target tables: {sorted(scanner.target_tables)}\n"
                "Hint: use --transformation-name to pick a specific instance "
                "if the same target appears more than once."
            )

        # ── collect target fields ────────────────────────────────────────────
        field_names = scanner.get_target_field_list(target_table)
        if not field_names:
            raise RuntimeError(
                f"No TARGETFIELD nodes found for '{target_table}'. "
                "Check that the TARGET definition is in the same folder."
            )

        print(f"Fields  : {len(field_names)}")

        # ── process each field ───────────────────────────────────────────────
        # Write partial results to a temp file as we go (handles large mappings)
        tmp_path = Path(output_path).with_suffix(".tmp.md")
        tmp_path.parent.mkdir(parents=True, exist_ok=True)

        specs: List[Dict[str, Any]] = []
        mm, target_instance = pairs[0]   # use first matching pair
        builder = FieldSpecBuilder(scanner)

        total = len(field_names)
        for idx, fname in enumerate(field_names, 1):
            if idx % 20 == 0 or idx == total:
                print(f"  [{idx}/{total}] {fname}")
            try:
                spec = builder.build(fname, target_table, mm, target_instance)
            except Exception as exc:
                print(f"  WARN: field {fname} failed – {exc}", file=sys.stderr)
                spec = {
                    "target_field":    f"{target_table}.{fname}",
                    "primary_sources": ["(error)"],
                    "lineage_chain":   [],
                    "intermediates":   [],
                    "conditions":      {"join":[], "filter":[], "additional":[]},
                    "referential":     [],
                    "is_seq_gen":      False,
                }
            specs.append(spec)

            # Write partial to temp file every 10 fields
            if idx % 10 == 0:
                tmp_path.write_text(
                    MarkdownRenderer.render(specs, target_table),
                    encoding="utf-8",
                )

        # ── render final MD ──────────────────────────────────────────────────
        md = MarkdownRenderer.render(specs, target_table)
        Path(output_path).write_text(md, encoding="utf-8")
        if tmp_path.exists():
            tmp_path.unlink()

        # ── cross-session diagnostics ───────────────────────────────────────
        if not scanner.session_order:
            print(
                "\nNOTE: no WORKFLOW/SESSION nodes found in this JSON — "
                "cross-session backtracking could not use real execution "
                "order. If a table is written by more than one mapping, "
                "the choice of 'upstream session' may be a best-effort "
                "guess rather than a verified one. Export the WORKFLOW "
                "along with the mapping(s) to enable order-aware tracing."
            )
        ambiguous = getattr(scanner, "last_ambiguous_tables", None)
        if ambiguous:
            print("\nWARNING: ambiguous cross-session lineage detected:")
            for tname, mapping_names in ambiguous.items():
                print(
                    f"  Table '{tname}' is written as a TARGET by multiple "
                    f"mappings: {mapping_names}. Picked '{mapping_names[0]}' "
                    f"as upstream (first match) — verify this is correct."
                )

        print(f"\nDone → {output_path}")

    def _get_folder(self, folder_name: Optional[str]) -> Dict:
        repos = _children(self.powermart, "REPOSITORY")
        if not repos:
            repos = [self.powermart]
        for repo in repos:
            for folder in _children(repo, "FOLDER"):
                if not folder_name or _attr(folder, "NAME") == folder_name:
                    return folder
        raise RuntimeError(
            f"Folder '{folder_name}' not found."
            if folder_name
            else "No FOLDER node found in JSON."
        )


# ════════════════════════════════════════════════════════════════════════════
# SECTION 12 – CLI
# ════════════════════════════════════════════════════════════════════════════

def main() -> None:
    ap = argparse.ArgumentParser(
        prog="informatica_lineage_md.py",
        description="Generate field-level lineage Markdown from Informatica JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples
--------
  # Basic usage
  python informatica_lineage_md.py -j mapping.json -t CUSTOMER_STG

  # Disambiguate when same target table appears twice in a mapping
  python informatica_lineage_md.py -j mapping.json -t CUSTOMER_STG \\
      --transformation-name CUSTOMER_STG_2

  # Specify folder and output file
  python informatica_lineage_md.py -j mapping.json -t ORDERS \\
      --folder ETL_FOLDER -o orders_lineage.md
""",
    )
    ap.add_argument("-j", "--json",   required=True,  help="Path to Informatica JSON file")
    ap.add_argument("-t", "--target", required=True,  help="Target table name")
    ap.add_argument(
        "--transformation-name", "--transformation_name",
        dest="transformation_name", default=None,
        help="Target INSTANCE name when the same target table appears multiple times",
    )
    ap.add_argument("--folder", default=None, help="Folder name (uses first if omitted)")
    ap.add_argument("-o", "--output", default=None, help="Output .md file path")

    args = ap.parse_args()

    output = args.output or (
        f"lineage_{args.target}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    )

    Orchestrator(args.json).run(
        target_table=args.target,
        folder_name=args.folder,
        transformation_name=args.transformation_name,
        output_path=output,
    )


if __name__ == "__main__":
    main()
