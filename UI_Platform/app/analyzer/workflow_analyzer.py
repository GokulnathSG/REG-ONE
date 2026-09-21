"""Deterministic, graph-algorithm-based analysis over the parsed domain
model. No LLM / heuristic inference lives here on purpose (see TDD Section
3.9) — everything is derived from explicit structure in the export
(WORKFLOWLINK edges, CONNECTOR edges, INSTANCE membership).
"""
from collections import defaultdict, deque
from typing import List, Dict

from app.models.domain import RepositoryModel


def compute_execution_order(repo: RepositoryModel) -> List[str]:
    """Topological sort of TASKINSTANCE nodes using WORKFLOWLINK edges.
    Falls back to declaration order (with a warning) if a cycle is found."""
    wf = repo.workflow
    if wf is None:
        return []

    nodes = [t.name for t in wf.task_instances]
    node_set = set(nodes)
    edges = [(l.from_task, l.to_task) for l in wf.links if l.from_task in node_set and l.to_task in node_set]

    indeg = {n: 0 for n in nodes}
    adj = defaultdict(list)
    for a, b in edges:
        adj[a].append(b)
        indeg[b] += 1

    queue = deque(sorted(n for n in nodes if indeg[n] == 0))
    order = []
    indeg_work = dict(indeg)
    while queue:
        n = queue.popleft()
        order.append(n)
        for nxt in sorted(adj[n]):
            indeg_work[nxt] -= 1
            if indeg_work[nxt] == 0:
                queue.append(nxt)

    if len(order) != len(nodes):
        wf.warnings.append(
            "Circular dependency detected among workflow tasks; execution order fell back to declaration order.")
        return nodes
    wf.execution_order = order
    return order


def build_execution_table(repo: RepositoryModel) -> List[Dict]:
    """Row-per-transformation, execution-ordered, for Table View (Section 4.2.3
    of the TDD). Includes a Mapplet column only when at least one mapplet is used."""
    wf = repo.workflow
    if wf is None:
        return []
    order = wf.execution_order or compute_execution_order(repo)
    ti_by_name = {t.name: t for t in wf.task_instances}

    rows = []
    for task_name in order:
        ti = ti_by_name.get(task_name)
        if ti is None or ti.task_type != "Session":
            continue
        session = wf.sessions.get(ti.task_name)
        if session is None:
            continue
        mapping = repo.mappings.get(session.mapping_name)
        if mapping is None:
            rows.append({"workflow": wf.name, "session": session.name,
                         "mapping": session.mapping_name, "mapplet": "", "transformation": "(mapping not found)"})
            continue
        if mapping.mapplets:
            for mplt_name in mapping.mapplets:
                mplt = repo.mapplets.get(mplt_name)
                t_names = mplt.transformations if mplt else []
                for tname in (t_names or [mplt_name]):
                    rows.append({"workflow": wf.name, "session": session.name, "mapping": mapping.name,
                                 "mapplet": mplt_name, "transformation": tname})
            for tname in mapping.transformations:
                rows.append({"workflow": wf.name, "session": session.name, "mapping": mapping.name,
                             "mapplet": "", "transformation": tname})
        else:
            for tname in mapping.transformations:
                rows.append({"workflow": wf.name, "session": session.name, "mapping": mapping.name,
                             "mapplet": "", "transformation": tname})
    return rows


def has_any_mapplet(repo: RepositoryModel) -> bool:
    return any(m.mapplets for m in repo.mappings.values())


def _ordered_lineage(instances, connectors) -> List[str]:
    """Ordered Source -> Transformation(s) -> Target chain for one
    Mapping/Mapplet canvas, derived by walking CONNECTOR edges from every
    source instance. Shared by build_mapping_lineage and
    build_mapplet_lineage since both operate on the same
    instances/connectors shape."""
    inst_by_name = {i.name: i for i in instances}
    adj = defaultdict(list)
    for c in connectors:
        adj[c.from_instance].append(c.to_instance)

    starts = [i.name for i in instances if i.type == "SOURCE"]
    visited = set()
    chain = []

    def label(inst_name):
        inst = inst_by_name.get(inst_name)
        return inst.ref_name if inst else inst_name

    def dfs(n):
        if n in visited:
            return
        visited.add(n)
        chain.append(label(n))
        for nxt in sorted(set(adj[n])):
            dfs(nxt)

    for s in sorted(starts):
        dfs(s)
    # Any instance not reached from a source (disconnected) still gets listed.
    for i in instances:
        if i.name not in visited:
            chain.append(label(i.name))
            visited.add(i.name)
    return chain


def build_mapping_lineage(repo: RepositoryModel, mapping_name: str) -> List[str]:
    """Ordered Source -> Transformation(s) -> Target chain for one mapping."""
    mapping = repo.mappings.get(mapping_name)
    if mapping is None:
        return []
    return _ordered_lineage(mapping.instances, mapping.connectors)


def build_mapplet_lineage(repo: RepositoryModel, mapplet_name: str) -> List[str]:
    """Same ordered lineage chain as build_mapping_lineage, but for a
    Mapplet's own canvas -- powers the Mapplet drill-down visual (Table
    View's Mapplet column) the same way build_mapping_lineage powers the
    Mapping drill-down."""
    mapplet = repo.mapplets.get(mapplet_name)
    if mapplet is None:
        return []
    return _ordered_lineage(mapplet.instances, mapplet.connectors)


def all_mapping_lineages(repo: RepositoryModel) -> Dict[str, List[str]]:
    return {name: build_mapping_lineage(repo, name) for name in repo.mappings}


def all_mapplet_lineages(repo: RepositoryModel) -> Dict[str, List[str]]:
    return {name: build_mapplet_lineage(repo, name) for name in repo.mapplets}


def _is_source_qualifier(inst) -> bool:
    """A Source Qualifier (SQ) instance is the transformation that one or
    more raw SOURCE instances feed into (Informatica lets a single SQ take
    2..n source tables, e.g. a homogeneous join). Detected by ref_type first
    (works for both XML and JSON exports); falls back to the conventional
    'SQ_' naming prefix if ref_type wasn't populated by the parser."""
    if inst is None or inst.type != "TRANSFORMATION":
        return False
    ref_type = (inst.ref_type or "").lower()
    if "source qualifier" in ref_type:
        return True
    return inst.name.upper().startswith("SQ_")


def find_unused_transformations(repo: RepositoryModel, mapping_name: str) -> List[str]:
    """Transformation instances that are present on the mapping canvas but
    have zero CONNECTOR edges touching them (neither incoming nor outgoing).
    These can never appear in any Source->Target lineage branch because
    nothing feeds them and they feed nothing -- they're dropped on the
    canvas but never wired into the data flow."""
    mapping = repo.mappings.get(mapping_name)
    if mapping is None:
        return []
    connected = set()
    for c in mapping.connectors:
        connected.add(c.from_instance)
        connected.add(c.to_instance)
    unused = sorted({
        (i.ref_name or i.name)
        for i in mapping.instances
        if i.type == "TRANSFORMATION" and i.name not in connected
    })
    return unused


def build_mapping_lineage_by_source_qualifier(repo: RepositoryModel, mapping_name: str) -> List[Dict]:
    """One entry per Source Qualifier in the mapping (instead of one merged
    chain for the whole mapping). Each entry carries just the source
    table(s) feeding that specific SQ (2..n, per Informatica semantics),
    the target(s) that branch actually reaches, and the full ordered
    Source -> Transformation(s) -> Target lineage for that branch only.

    Returns: [{"source_qualifier": str, "sources": [...], "targets": [...],
                "lineage": [...]}]
    """
    mapping = repo.mappings.get(mapping_name)
    if mapping is None:
        return []
    inst_by_name = {i.name: i for i in mapping.instances}
    # Informatica emits one CONNECTOR per FIELD, so the same instance pair
    # (e.g. EXP_A -> EXP_B) can appear dozens of times -- once per port that
    # crosses that pipe. succ/pred must be deduplicated to unique instance
    # pairs here, at the source: the indegree count below and the Kahn
    # decrement step later both need to agree on "one edge per instance
    # pair", or indegree never reaches zero for any multi-field connection
    # and every branch with more than one field on a pipe gets misreported
    # as cyclic.
    succ = defaultdict(set)
    pred = defaultdict(set)
    for c in mapping.connectors:
        succ[c.from_instance].add(c.to_instance)
        pred[c.to_instance].add(c.from_instance)

    def label(inst_name):
        inst = inst_by_name.get(inst_name)
        return inst.ref_name if inst else inst_name

    def trace_branch(root_names, seed_labels_ignored=None):
        """Builds the branch's node set (roots + everything forward-reachable
        from them) and orders it with a topological sort (Kahn's algorithm)
        instead of a plain DFS. A DFS pre-order can print a node -- e.g. a
        Lookup that also feeds a later step -- before every one of its real
        predecessors has been placed, and gives no guarantee that a sink
        (the Target) ends up last. A topological sort guarantees every node
        is only emitted after ALL of its predecessors within this branch
        have already been emitted, so the chain always finishes at the
        actual Target(s) and lookups land exactly where their dependencies
        place them, not shoved to the end.

        BFS discovery order (distance from the roots) is used as the tie
        -- break at every step, instead of alphabetical name. This keeps the
        printed order matching the real left-to-right pipeline shape even
        when several nodes become "ready" at once. Alphabetical tie-breaking
        used to mean two nodes at the same depth could print in an order
        that has nothing to do with the data flow.

        If a cycle exists anywhere in the branch (a transformation loops
        back into an earlier step -- e.g. a mis-wired Router/Union, or a
        duplicated/reversed CONNECTOR in the export), Kahn's algorithm
        cannot linearize the cyclic nodes at all. Previously this silently
        dumped *every* unresolved node -- including ones downstream of the
        cycle, like the Target -- in pure alphabetical order, which could
        even print the Target before a transformation that feeds it. Now:
          - only the nodes actually inside/blocked-by the cycle are handled
            specially, ordered by BFS discovery order (not alphabetically)
            so they still read left-to-right;
          - a warning naming those exact transformations is recorded so the
            cycle is visible instead of silently misordering the chain;
          - Target instance(s) are always forced to the very end of the
            chain regardless of where the cycle sits, since a Target can
            never legitimately feed anything else."""
        reachable = set(root_names)
        discovery_order = {}
        queue = deque()
        for r in sorted(root_names):
            if r not in discovery_order:
                discovery_order[r] = len(discovery_order)
                queue.append(r)
        while queue:
            n = queue.popleft()
            for nxt in sorted(set(succ.get(n, []))):
                if nxt not in reachable:
                    reachable.add(nxt)
                if nxt not in discovery_order:
                    discovery_order[nxt] = len(discovery_order)
                    queue.append(nxt)

        indeg = {n: 0 for n in reachable}
        for n in reachable:
            for nxt in succ.get(n, []):
                if nxt in reachable:
                    indeg[nxt] += 1

        def by_discovery(n):
            return discovery_order.get(n, len(discovery_order))

        ready = sorted((n for n in reachable if indeg[n] == 0), key=by_discovery)
        indeg_work = dict(indeg)
        order = []
        while ready:
            ready.sort(key=by_discovery)
            n = ready.pop(0)
            order.append(n)
            for nxt in sorted(set(succ.get(n, [])), key=by_discovery):
                if nxt in reachable:
                    indeg_work[nxt] -= 1
                    if indeg_work[nxt] == 0:
                        ready.append(nxt)

        cyclic_nodes = [n for n in reachable if n not in order]
        if cyclic_nodes:
            cyclic_nodes.sort(key=by_discovery)
            non_target = [n for n in cyclic_nodes
                          if not (inst_by_name.get(n) and inst_by_name[n].type == "TARGET")]
            targets_in_cycle = [n for n in cyclic_nodes if n not in non_target]
            order.extend(non_target)
            order.extend(targets_in_cycle)
            repo.warnings.append(
                f"Mapping '{mapping.name}': a cycle was detected among "
                f"{[label(n) for n in non_target]} (branch rooted at "
                f"{[label(r) for r in root_names]}). These could not be put in "
                "a strict Source->Target order and were listed in flow-discovery "
                "order instead; please verify this connector path in Designer."
            )
        else:
            # No cycle, but guarantee Target(s) are still last even if a
            # disconnected/parallel piece of the branch left one earlier.
            targets = [n for n in order if inst_by_name.get(n) and inst_by_name[n].type == "TARGET"]
            if targets:
                non_targets = [n for n in order if n not in targets]
                order = non_targets + sorted(targets, key=by_discovery)

        chain = [label(n) for n in order]
        targets_reached = [label(n) for n in order
                            if inst_by_name.get(n) and inst_by_name[n].type == "TARGET"]
        return chain, targets_reached

    sq_instances = [i for i in mapping.instances if _is_source_qualifier(i)]

    rows = []
    if sq_instances:
        for sq in sorted(sq_instances, key=lambda i: i.name):
            src_names = sorted(set(pred.get(sq.name, [])))
            source_only_names = [s for s in src_names
                                  if inst_by_name.get(s) and inst_by_name[s].type == "SOURCE"]
            src_labels = [label(s) for s in source_only_names]
            # Roots must be actual SOURCE instances only. A Source Qualifier
            # should never legitimately have a non-SOURCE predecessor; if one
            # shows up here it's a back-edge (cycle) feeding into the SQ, and
            # treating it as a "root" would distort the branch's start point.
            roots = list(source_only_names) + [sq.name]
            chain, targets_reached = trace_branch(roots)
            rows.append({
                "source_qualifier": sq.name,
                "sources": src_labels,
                "targets": sorted(set(targets_reached)),
                "lineage": chain,
            })
    else:
        # No explicit SQ instance in this mapping (parser didn't tag one) --
        # fall back to one row per raw SOURCE instance so nothing is lost.
        for s in sorted((i for i in mapping.instances if i.type == "SOURCE"), key=lambda i: i.name):
            chain, targets_reached = trace_branch([s.name])
            rows.append({
                "source_qualifier": s.name,
                "sources": [label(s.name)],
                "targets": sorted(set(targets_reached)),
                "lineage": chain,
            })
    return rows
