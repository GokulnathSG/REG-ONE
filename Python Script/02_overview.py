import xml.etree.ElementTree as ET
import json
import argparse
from collections import defaultdict, deque, OrderedDict


def attr(elem, name, default=""):
    return elem.attrib.get(name, default)


def direct_children(parent, tag):
    return [child for child in list(parent) if child.tag == tag]


def unique_preserve_order(items):
    seen = set()
    result = []

    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)

    return result


def suppress_repeating_values(rows, keys):
    """Blank repeated values in consecutive rows for presentation-friendly tables."""
    previous = {k: None for k in keys}

    for row in rows:
        for key in keys:
            value = row.get(key, "")
            if value == previous[key]:
                row[key] = ""
            else:
                previous[key] = value

    return rows


def build_session_lookup(root):
    """
    session_lookup[session_name] = mapping_name
    """
    session_lookup = {}

    for session in root.findall(".//SESSION"):
        session_name = attr(session, "NAME")
        mapping_name = attr(session, "MAPPINGNAME")

        if session_name:
            session_lookup[session_name] = mapping_name

    return session_lookup


def get_mapping_elements(root):
    """
    OrderedDict[mapping_name] = mapping_element
    """
    mappings = OrderedDict()

    for mapping in root.findall(".//MAPPING"):
        mapping_name = attr(mapping, "NAME")

        if mapping_name:
            mappings[mapping_name] = mapping

    return mappings


def get_xml_transformation_order(mapping_elem):
    """
    Fallback transformation order based on XML physical order.
    """
    return [
        attr(t, "NAME")
        for t in direct_children(mapping_elem, "TRANSFORMATION")
        if attr(t, "NAME")
    ]


def get_connector_runtime_transformation_order(mapping_elem):
    """
    Derives transformation runtime/data-flow order from CONNECTOR flow.

    Output includes only transformation names.
    Source and target instances are used only to calculate order.
    """

    transformation_defs = OrderedDict()

    for transformation in direct_children(mapping_elem, "TRANSFORMATION"):
        transformation_name = attr(transformation, "NAME")

        if transformation_name:
            transformation_defs[transformation_name] = {
                "type": attr(transformation, "TYPE")
            }

    xml_trans_order = list(transformation_defs.keys())

    instance_to_transformation = {}

    for inst in direct_children(mapping_elem, "INSTANCE"):
        instance_name = attr(inst, "NAME")
        transformation_name = attr(inst, "TRANSFORMATION_NAME")

        if instance_name and transformation_name:
            instance_to_transformation[instance_name] = transformation_name
        elif instance_name:
            instance_to_transformation[instance_name] = instance_name

    connectors = direct_children(mapping_elem, "CONNECTOR")

    if not connectors:
        return xml_trans_order

    graph = defaultdict(list)
    indegree = defaultdict(int)
    node_order = []

    def add_node(node):
        if node and node not in node_order:
            node_order.append(node)
        if node:
            indegree[node] = indegree[node]

    for inst_name in instance_to_transformation:
        add_node(inst_name)

    for transformation_name in xml_trans_order:
        add_node(transformation_name)

    for conn in connectors:
        from_inst = attr(conn, "FROMINSTANCE")
        to_inst = attr(conn, "TOINSTANCE")

        if not from_inst or not to_inst:
            continue

        add_node(from_inst)
        add_node(to_inst)

        if to_inst not in graph[from_inst]:
            graph[from_inst].append(to_inst)
            indegree[to_inst] += 1

    queue = deque([node for node in node_order if indegree[node] == 0])
    topo_nodes = []

    while queue:
        node = queue.popleft()
        topo_nodes.append(node)

        for next_node in graph[node]:
            indegree[next_node] -= 1

            if indegree[next_node] == 0:
                queue.append(next_node)

    # Handle cycles or unusual connector structures
    for node in node_order:
        if node not in topo_nodes:
            topo_nodes.append(node)

    ordered_transformations = []

    for node in topo_nodes:
        mapped_transformation = instance_to_transformation.get(node, node)

        if mapped_transformation in transformation_defs:
            ordered_transformations.append(mapped_transformation)

    ordered_transformations = unique_preserve_order(ordered_transformations)

    # Append disconnected transformations in XML order
    for transformation_name in xml_trans_order:
        if transformation_name not in ordered_transformations:
            ordered_transformations.append(transformation_name)

    return ordered_transformations


def get_task_instance_session_map(workflow_elem):
    """
    Maps TASKINSTANCE name and task name to actual session name.
    """
    task_instance_to_session = {}

    for task_inst in direct_children(workflow_elem, "TASKINSTANCE"):
        task_type = attr(task_inst, "TASKTYPE")
        instance_name = attr(task_inst, "NAME")
        task_name = attr(task_inst, "TASKNAME")

        if task_type == "Session":
            session_name = task_name or instance_name

            if instance_name:
                task_instance_to_session[instance_name] = session_name

            if task_name:
                task_instance_to_session[task_name] = session_name

    return task_instance_to_session


def get_workflow_session_links_runtime_order(workflow_elem, session_lookup):
    """
    Derives session-to-session runtime order from WORKFLOWLINK.

    Includes condition between sessions.
    """

    task_instance_to_session = get_task_instance_session_map(workflow_elem)

    links = direct_children(workflow_elem, "WORKFLOWLINK")

    adjacency = defaultdict(list)

    for link in links:
        from_task = attr(link, "FROMTASK")
        to_task = attr(link, "TOTASK")
        condition = attr(link, "CONDITION")

        if from_task and to_task:
            adjacency[from_task].append({
                "to_task": to_task,
                "condition": condition
            })

    runtime_links = []
    visited_edges = set()

    def walk(from_task):
        for link_info in adjacency.get(from_task, []):
            to_task = link_info["to_task"]
            condition = link_info["condition"]

            edge_key = (from_task, to_task, condition)

            if edge_key in visited_edges:
                continue

            visited_edges.add(edge_key)

            from_session = task_instance_to_session.get(from_task, "Start" if from_task == "Start" else from_task)
            to_session = task_instance_to_session.get(to_task, to_task)

            if to_task in task_instance_to_session:
                mapping_name = session_lookup.get(to_session, "")

                runtime_links.append({
                    "from_session": from_session,
                    "to_session": to_session,
                    "condition": condition if condition else "[condition: none defined]",
                    "mapping_name": mapping_name
                })

            walk(to_task)

    if "Start" in adjacency:
        walk("Start")
    else:
        # Fallback if Start is not available
        for link in links:
            from_task = attr(link, "FROMTASK")
            to_task = attr(link, "TOTASK")
            condition = attr(link, "CONDITION")

            from_session = task_instance_to_session.get(from_task, from_task)
            to_session = task_instance_to_session.get(to_task, to_task)

            if to_task in task_instance_to_session:
                mapping_name = session_lookup.get(to_session, "")

                runtime_links.append({
                    "from_session": from_session,
                    "to_session": to_session,
                    "condition": condition if condition else "[condition: none defined]",
                    "mapping_name": mapping_name
                })

    return runtime_links


def build_workflow_session_mapping_transformation_table(
    root,
    session_lookup,
    mapping_runtime_orders
):
    """Build runtime-ordered workflow/session/mapping/transformation table."""

    rows = []
    workflows = root.findall(".//WORKFLOW")

    if workflows:
        for workflow in workflows:
            workflow_name = attr(workflow, "NAME")

            session_links = get_workflow_session_links_runtime_order(
                workflow,
                session_lookup
            )

            for session_link in session_links:
                to_session = session_link["to_session"]
                mapping_name = session_link["mapping_name"]

                transformations = mapping_runtime_orders.get(mapping_name, [])

                if transformations:
                    for transformation_name in transformations:
                        rows.append({
                            "Workflow Name": workflow_name,
                            "Session Name": to_session,
                            "Mapping Name": mapping_name,
                            "Transformation Name": transformation_name
                        })
                else:
                    rows.append({
                        "Workflow Name": workflow_name,
                        "Session Name": to_session,
                        "Mapping Name": mapping_name,
                        "Transformation Name": ""
                    })

    else:
        # Fallback if no WORKFLOW exists
        for session_name, mapping_name in session_lookup.items():
            transformations = mapping_runtime_orders.get(mapping_name, [])

            if transformations:
                for transformation_name in transformations:
                    rows.append({
                        "Workflow Name": "",
                        "Session Name": session_name,
                        "Mapping Name": mapping_name,
                        "Transformation Name": transformation_name
                    })
            else:
                rows.append({
                    "Workflow Name": "",
                    "Session Name": session_name,
                    "Mapping Name": mapping_name,
                    "Transformation Name": ""
                })

    return suppress_repeating_values(rows, ["Workflow Name", "Session Name", "Mapping Name"])


def build_session_condition_table(root, session_lookup):
    """
    Separate clean table only for session dependency conditions.
    """

    rows = []
    workflows = root.findall(".//WORKFLOW")

    for workflow in workflows:
        workflow_name = attr(workflow, "NAME")

        session_links = get_workflow_session_links_runtime_order(
            workflow,
            session_lookup
        )

        for session_link in session_links:
            rows.append({
                "Workflow Name": workflow_name,
                "From Session": session_link["from_session"],
                "To Session": session_link["to_session"],
                "Condition": session_link["condition"]
            })

    return rows


def build_mapping_transformation_table(mapping_runtime_orders):
    rows = []

    for mapping_name, transformations in mapping_runtime_orders.items():
        if transformations:
            for transformation_name in transformations:
                rows.append({
                    "Mapping Name": mapping_name,
                    "Transformation Name": transformation_name
                })
        else:
            rows.append({
                "Mapping Name": mapping_name,
                "Transformation Name": ""
            })

    return suppress_repeating_values(rows, ["Mapping Name"])


def build_mapping_flowcharts(mapping_runtime_orders):
    flowcharts = []

    for mapping_name, transformations in mapping_runtime_orders.items():
        flowchart_text = " -> ".join(transformations) if transformations else ""

        flowcharts.append({
            "Mapping Heading": mapping_name,
            "Flowchart": flowchart_text
        })

    return flowcharts


def get_source_tables_from_mapping(mapping_elem):
    """
    Extract source table names from a mapping.
    Returns list of source table names.
    """
    source_tables = []

    for inst in direct_children(mapping_elem, "INSTANCE"):
        inst_type = attr(inst, "TYPE")
        transformation_type = attr(inst, "TRANSFORMATION_TYPE")
        
        if inst_type == "SOURCE" and transformation_type == "Source Definition":
            transformation_name = attr(inst, "TRANSFORMATION_NAME")
            if transformation_name:
                source_tables.append(transformation_name)

    return source_tables


def get_target_tables_from_mapping(mapping_elem):
    """
    Extract target table names from a mapping.
    Returns OrderedDict of target instance -> target table name.
    """
    target_tables = OrderedDict()

    for inst in direct_children(mapping_elem, "INSTANCE"):
        inst_type = attr(inst, "TYPE")
        transformation_type = attr(inst, "TRANSFORMATION_TYPE")
        
        if inst_type == "TARGET" and transformation_type == "Target Definition":
            inst_name = attr(inst, "NAME")
            transformation_name = attr(inst, "TRANSFORMATION_NAME")
            if inst_name and transformation_name:
                target_tables[inst_name] = transformation_name

    return target_tables


def get_target_table_load_order(mapping_elem):
    """
    Get target load order from TARGETLOADORDER elements.
    Returns OrderedDict of target instance -> order number.
    """
    target_order = OrderedDict()

    for target_load in direct_children(mapping_elem, "TARGETLOADORDER"):
        target_instance = attr(target_load, "TARGETINSTANCE")
        order = attr(target_load, "ORDER")
        
        if target_instance and order:
            target_order[target_instance] = int(order)

    return target_order


def check_for_file_writer_exports(root):
    """
    Check for File Writer transformations in sessions that export data.
    Returns list of dicts with target table and file export info.
    """
    writers = []

    for session in root.findall(".//SESSION"):
        for session_ext in direct_children(session, "SESSIONEXTENSION"):
            ext_type = attr(session_ext, "TYPE")
            ext_subtype = attr(session_ext, "SUBTYPE")
            
            if ext_type == "WRITER" and "File" in ext_subtype:
                instance_name = attr(session_ext, "SINSTANCENAME")
                output_filename = ""
                output_directory = ""
                
                # Extract file output information from ATTRIBUTE elements
                for attribute in direct_children(session_ext, "ATTRIBUTE"):
                    attr_name = attr(attribute, "NAME")
                    attr_value = attr(attribute, "VALUE")
                    
                    if attr_name == "Output filename":
                        output_filename = attr_value
                    elif attr_name == "Output file directory":
                        output_directory = attr_value
                
                if instance_name and (output_filename or output_directory):
                    writers.append({
                        "target_table": instance_name,
                        "output_filename": output_filename,
                        "output_directory": output_directory,
                        "export_type": ext_subtype
                    })

    return writers


def build_session_source_target_table(root, session_lookup, mapping_elements):
    """
    Build table: Session Name, Source Table(s), Target Table(s)
    Also returns session flow order.
    """
    rows = []
    session_flow = []
    workflows = root.findall(".//WORKFLOW")

    if workflows:
        for workflow in workflows:
            workflow_name = attr(workflow, "NAME")
            
            session_links = get_workflow_session_links_runtime_order(
                workflow,
                session_lookup
            )

            for idx, session_link in enumerate(session_links):
                to_session = session_link["to_session"]
                mapping_name = session_link["mapping_name"]
                
                if mapping_name in mapping_elements:
                    mapping_elem = mapping_elements[mapping_name]
                    
                    source_tables = get_source_tables_from_mapping(mapping_elem)
                    target_tables = get_target_tables_from_mapping(mapping_elem)
                    target_order = get_target_table_load_order(mapping_elem)
                    
                    # Get ordered target tables
                    ordered_targets = []
                    if target_order:
                        sorted_targets = sorted(target_order.items(), key=lambda x: x[1])
                        ordered_targets = [target_tables.get(inst, inst) for inst, _ in sorted_targets if inst in target_tables]
                    else:
                        ordered_targets = list(target_tables.values())
                    
                    source_str = ", ".join(source_tables) if source_tables else ""
                    target_str = ", ".join(ordered_targets) if ordered_targets else ""
                    
                    rows.append({
                        "Session Name": to_session,
                        "Mapping Name": mapping_name,
                        "Source Table": source_str,
                        "Target Table": target_str
                    })
                    
                    # Add to session flow
                    if idx == 0:
                        session_flow.append({
                            "order": idx + 1,
                            "session": to_session,
                            "source_tables": source_tables,
                            "target_tables": ordered_targets
                        })
                    else:
                        session_flow.append({
                            "order": idx + 1,
                            "session": to_session,
                            "source_tables": source_tables,
                            "target_tables": ordered_targets
                        })

    return suppress_repeating_values(rows, ["Session Name", "Mapping Name"]), session_flow


def build_session_table_flowchart(session_source_target_data):
    """
    Build flowchart from session flow data showing table progression.
    Format: source_table -> target_table -> next_source_table -> ...
    """
    if not session_source_target_data:
        return ""

    flowchart_parts = []

    for session_info in session_source_target_data:
        sources = session_info.get("source_tables", [])
        targets = session_info.get("target_tables", [])
        
        # Add source tables
        for src in sources:
            flowchart_parts.append(src)
        
        # Add target tables
        for tgt in targets:
            flowchart_parts.append(tgt)

    return " -> ".join(flowchart_parts) if flowchart_parts else ""


def build_session_execution_flowchart(session_source_target_data):
    """
    Build simple flowchart showing session execution order.
    Format: Session1 -> Session2 -> Session3
    """
    if not session_source_target_data:
        return ""

    sessions = [item["session"] for item in session_source_target_data]
    return " -> ".join(sessions) if sessions else ""


def build_writer_export_table(root, session_lookup=None, mapping_elements=None):
    """
    Build export table for File Writer transformations.
    Returns list of dicts with target table and export file info.
    """
    writers = check_for_file_writer_exports(root)
    
    rows = []
    for writer in writers:
        rows.append({
            "Target Table": writer["target_table"],
            "Export Filename": writer["output_filename"],
            "Export Directory": writer["output_directory"],
            "Export Type": writer["export_type"],
            "Purpose": "Reporting Export"
        })
    
    return rows if rows else None


def extract_runtime_json(xml_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()

    session_lookup = build_session_lookup(root)
    mappings = get_mapping_elements(root)

    mapping_runtime_orders = OrderedDict()

    for mapping_name, mapping_elem in mappings.items():
        mapping_runtime_orders[mapping_name] = get_connector_runtime_transformation_order(
            mapping_elem
        )

    # Build new sections
    session_source_target_table, session_flow = build_session_source_target_table(
        root,
        session_lookup,
        mappings
    )
    
    session_execution_flowchart = build_session_execution_flowchart(session_flow)
    session_table_flowchart = build_session_table_flowchart(session_flow)
    
    writer_export_table = build_writer_export_table(root)

    output = {
        "workflow_session_mapping_transformation_table": build_workflow_session_mapping_transformation_table(
            root,
            session_lookup,
            mapping_runtime_orders
        ),

        "mapping_flowcharts": build_mapping_flowcharts(
            mapping_runtime_orders
        ),
        
        "section_3_session_source_target_table": session_source_target_table,
        
        "section_3_session_execution_flowchart": session_execution_flowchart,
        
        "section_3_session_table_flowchart": session_table_flowchart
    }
    
    if writer_export_table:
        output["section_4_writer_export_table"] = writer_export_table

    return output


def main():
    parser = argparse.ArgumentParser(
        description="Extract Informatica runtime workflow/session/mapping/transformation details to JSON."
    )

    parser.add_argument(
        "xml_file",
        help="Input Informatica PowerCenter XML file"
    )

    parser.add_argument(
        "-o",
        "--output",
        help="Output JSON file path. If not provided, JSON is printed to console."
    )

    args = parser.parse_args()

    result = extract_runtime_json(args.xml_file)

    json_text = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(json_text)
    else:
        print(json_text)


if __name__ == "__main__":
    main()
