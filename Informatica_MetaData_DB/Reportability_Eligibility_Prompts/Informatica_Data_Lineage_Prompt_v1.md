# Informatica Data Lineage Extraction Prompt

**How to use:** Paste this entire prompt into your LLM chat, then attach your two input files:
1. The Excel workbook (Tab-1 "Overview" + Tab-2 "Transformation-wise")
2. The Informatica Workflow Export XML

Then replace the placeholders at the bottom (`<TARGET_TABLE_NAME>` and `<TARGET_INSTANCE/TRANSFORMATION_NAME>`) with your actual values before sending.

---

## PROMPT

You are a **Data Lineage Analyst** specializing in Informatica PowerCenter metadata. You will be given two inputs:

1. **Excel workbook** with two tabs:
   - **Tab-1 (Overview):** columns `Session`, `Mapping`, `Transformation` — a high-level index of every session/mapping/transformation in scope.
   - **Tab-2 (Transformation-wise):** columns `Session`, `Mapping`, `Transformation`, `Logic` — per-transformation business logic/expressions, one tab per transformation (or one consolidated sheet listing all transformations with their logic).

2. **XML Workflow Export** — the raw Informatica repository export containing `<SESSION>`, `<MAPPING>`, `<TRANSFORMATION>`, `<TRANSFORMFIELD>`, `<INSTANCE>`, and `<CONNECTOR>` elements that define the physical port-to-port connections between every transformation instance in every mapping.

### Your task

I will specify a **Target Table** and a specific **Instance/Transformation** feeding it. For **every field** in that target table/instance, you must:

#### Step 1 — Build the connector graph from XML
Parse the XML and, for the specified target, build the full backward connector chain: for every target field (`TOFIELD`), find the `<CONNECTOR>` entries where `TOINSTANCE` matches, and resolve the `FROMINSTANCE`/`FROMFIELD`. Continue resolving backward, instance by instance, transformation by transformation, session by session (a source in one session can be the target of an upstream session — chain across sessions/mappings, i.e. traverse n, n-1, n-2 … until you reach a physical **Source Qualifier / Source Definition** with no further upstream connector). This is the **primary source**.

#### Step 2 — Attach logic at each hop
For any transformation in the chain that is NOT a pure pass-through (i.e. Expression, Lookup, Router, Filter, Aggregator, Joiner, Union, etc.), pull its logic/expression:
- First check from Tab-2 to the last tab of the Excel for the documented logic text for that Session+Mapping+Transformation.
- If not found in Excel, extract the expression directly from the XML `<TRANSFORMFIELD>` `EXPRESSION` attribute (or lookup condition / router group condition / join condition as applicable).
- Record this as one "Logic/Rule" step, in the order encountered while tracing backward from target to source.

#### Step 3 — Recursively resolve every field referenced inside logic
If a logic expression references **more than one input field/port** (e.g. `IIF(A > 0, B, C)` references A, B, and C), do NOT stop at that transformation. Each referenced field (A, B, C) must **independently** be traced backward through Steps 1–2 all the way to its own primary source, exactly like the main field. This can pull in fields from other upstream mappings/sessions — trace those too.

#### Step 4 — Output format
Produce **exactly one row per target field** (not per source field). If a field has multiple independent contributing source paths (fan-in), consolidate all of them into that single row using **labeled branches**: `Path1:`, `Path2:`, `Path3:`, etc.

| Column | Description |
|---|---|
| `Target_Table_Name` | The target table specified by the user |
| `Field_Name` | The target field name |
| `Data_Lineage` | All paths for this field, labeled and separated: `Path1: Primary_Source.Field -> Transformation1 -> ... -> Target_Table.Field; Path2: ...; Path3: ...`. If there's only one contributing path, still label it `Path1:` for consistency. |
| `Logic/Rule-1`, `Logic/Rule-2`, `Logic/Rule-3`, ... | Each `Logic/Rule-n` column corresponds to the **n-th hop position**, aligned across all paths. Since paths can have different lengths, a single `Logic/Rule-n` cell may contain logic from more than one path (whichever paths actually have a hop at that position) — always label each entry with its `PathX:` prefix so it stays traceable back to the matching branch in `Data_Lineage`. Within each path, hops still appear strictly in that path's own lineage order (never traversal/discovery order). Leave out a path's label at position n if that path has fewer than n hops. |

**Logic/Rule cell format** (per path entry within the cell):

```
PathX: <transformation_name>: <raw expression> | <resolved_ref_1>, <resolved_ref_2>, ...
```

Where each `resolved_ref` is `<source_name>.<field>` — `source_name` is whatever that referenced port actually resolves to one hop upstream (a **table name** if from a source/target, or a **transformation instance name** if from another transformation's output port). This is only the immediate upstream origin, not full resolution — full resolution lives in `Data_Lineage`.

If more than one path shares logic at the same hop position, separate the entries with `; ` inside the same cell.

**Example (illustrative only) — field_A fed by col1, col2 (via a Lookup), and col3:**

| Target_Table_Name | Field_Name | Data_Lineage | Logic/Rule-1 | Logic/Rule-2 |
|---|---|---|---|---|
| table_A | field_A | Path1: SRC_TBL1.col1 -> EXP_calc.field_name -> table_A.field_A; Path2: SRC_TBL2.col2 -> LKP_ref.field_name -> EXP_calc -> table_A.field_A; Path3: SRC_TBL3.col3 -> EXP_calc.field_name -> table_A.field_A | Path1: EXP_calc.field_name: IIF(col1>0, col2, col3) \| SRC_TBL1.col1, LKP_ref.col2, SRC_TBL3.col3; Path2: LKP_ref: LKP condition col2=ref_key \| SRC_TBL2.col2; Path3: EXP_calc.field_name: IIF(col1>0, col2, col3) \| SRC_TBL1.col1, LKP_ref.col2, SRC_TBL3.col3 | Path2: EXP_calc: IIF(col1>0, col2, col3) \| SRC_TBL1.col1, LKP_ref.col2, SRC_TBL3.col3 |

*(Path1 and Path3 only have one hop, so they don't appear in Logic/Rule-2 — only Path2 does, since its Lookup added an extra hop before reaching EXP_calc.)*

### Rules / edge cases
- **Mapplets must be expanded, not skipped.** Informatica XML represents a mapplet as its own object (a set of transformations, an `Input` transformation, and either an `Output` transformation or exposed output ports) that gets dropped into a mapping as a mapplet **instance**. When backward-tracing hits a mapplet instance:
  - Do NOT treat the mapplet instance as a single opaque black-box hop. Step *inside* it: resolve which internal transformation/port the mapplet's output port actually maps to, then continue the connector-chain backward through the mapplet's internal transformations exactly as you would in a regular mapping.
  - Continue until you reach the mapplet's `Input` transformation, then keep tracing backward across the mapplet boundary into whatever feeds that mapplet instance in the parent mapping.
  - Any Expression/Lookup/Router/etc. logic found *inside* the mapplet counts as a normal logic hop and gets its own `Logic/Rule-n` column, positioned correctly in lineage order — same rules as any other transformation. Prefix these with the mapplet name for clarity, e.g. `mplt_Enrich.EXP_calc: IIF(...)`.
  - If a mapplet is reused by multiple sessions/mappings, resolve it fresh each time based on that instance's actual upstream connections in that specific mapping — don't assume identical lineage across reuses.
  - Nested mapplets (a mapplet containing another mapplet) must be expanded recursively the same way.
- **De-duplicate before output.** A field can get re-encountered multiple times during backward traversal — e.g. a pass-through transformation visited twice, or the same source field pulled in once as a direct dependency and again as a nested logic-reference. Since output is now one row per target field, de-dup happens **at the Path level within that field's row**, before you assemble the `Data_Lineage` and `Logic/Rule-n` cells:
  - Treat two candidate paths as duplicates if they resolve to the **identical** end-to-end sequence of instances (same primary source, same hops, same target) — even if discovered via a different traversal order. Keep only one and give it a single `PathX` label.
  - If the same primary source field reaches the target through **genuinely different** transformation paths (different instances/hops), keep both as separate `PathX` branches — that's real fan-in, not a duplicate.
  - If two candidate paths are identical except for logic text differing only by formatting/whitespace, treat them as duplicates and keep one.
  - Never duplicate a `PathX` label or repeat the exact same path twice within one field's row.
  - Across different `Field_Name` rows, the same upstream field/path can legitimately reappear (e.g. two target fields both fed by the same source column) — that repetition across rows is expected and should NOT be removed.
- Never stop backward-tracing at an intermediate mapping boundary — always continue into the upstream session/mapping if the source of the current session is itself a target of another session.
- If a field's ultimate source is a flat file, sequence generator, or hardcoded/constant value (no upstream table), state that explicitly in `Data_Lineage` (e.g. `CONSTANT('X') -> EXP_calc -> table_A.field_A`) instead of leaving it blank.
- If the same primary source field feeds the target through two different paths, include both as separate rows.
- Keep transformation **instance names** (not generic types) in the lineage path so the user can cross-check against the XML/Excel.
- If logic text differs between Excel Tab-2 and the XML expression, prefer the Excel-documented logic but flag the discrepancy in a footnote after the table.
- If information for a hop is missing from both files, mark that segment as `[unresolved]` rather than guessing.

### Deliverable
Once the full trace is complete for all fields of the specified target, **generate a downloadable Excel file** containing this table (one sheet, all columns above, auto-filter enabled on the header row so I can filter by `Field_Name` and instantly see its full lineage plus the lineage of every field involved in its logic).

---

### Now trace the following:

- **Target Table:** `<TARGET_TABLE_NAME>`
- **Target Instance/Transformation:** `<TARGET_INSTANCE/TRANSFORMATION_NAME>`

Ask me only if the XML or Excel is missing information needed to resolve a specific hop — otherwise complete the full trace and produce the Excel file.
