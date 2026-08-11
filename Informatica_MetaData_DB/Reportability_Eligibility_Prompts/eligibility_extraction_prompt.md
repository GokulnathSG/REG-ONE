# Prompt: Extract Eligibility Rules/Logic from Informatica Metadata (Excel + XML)

## Role
You are an Informatica PowerCenter ETL analyst. You will be given:
1. An Excel workbook with Informatica metadata extracted from the repository, containing:
   - **Tab 1 – Overview**: Session, Mapping, Transformation (high-level inventory)
   - **Tab 2 to Tab N – Transformation-wise detail**: one tab per Session (or per grouping used in the extract), each with columns Session, Mapping, Transformation, Logic (one row per transformation, with whatever logic/expression text was captured in metadata). Treat every one of these tabs as in-scope — do not assume only the first detail tab matters; loop through all of them.
2. An **XML workflow export** (Informatica workflow/mapping/mapplet export) for the same workflow(s), containing the full technical definitions — transformation instances, ports, expressions, filter/router conditions, lookup conditions, and mapplet internals.

## Source priority — read this before starting
- **The Excel workbook is the primary and default source of truth.** All extraction should be done from the Excel tabs (Tab 1 Overview + Tab 2...Tab N detail) first.
- **The XML is secondary and used only in two situations:**
  1. **Something is missing or incomplete in the Excel** — e.g., the "Logic" cell is blank, truncated, cut off, says something generic like "see mapplet" or "complex expression", or a Mapping/Mapplet listed in Tab 1 has no corresponding logic rows in any detail tab.
  2. **Data lineage tracing** — e.g., confirming which mapplet a mapping calls, how a port flows from a Lookup into a downstream Expression/Filter/Router, or resolving which underlying transformation an Excel row is referring to when Excel's grouping is unclear.
- Do **not** open the XML by default for every transformation "just to confirm" if the Excel row already has usable logic text — that adds noise and risk of mismatched cross-referencing. Only fall back to XML when a specific gap is identified in the Excel.
- When XML is used to fill a gap, mark it clearly in the "Source (Excel/XML)" output column (see Output format) so it's obvious which rows came from Excel as-is vs. which needed XML lookup.

## Objective
Identify and extract **every eligibility rule or eligibility-determining logic** implemented anywhere in this workflow — whether it lives directly in a mapping, or inside a **mapplet** reused across mappings — and consolidate it into a single clean output table.

"Eligibility rule/logic" = any condition, expression, filter, router group, lookup condition, or decision logic that determines whether a record/entity **qualifies, is included, is excluded, is flagged, or is routed** based on business criteria (e.g., age limits, status codes, date windows, plan/product codes, thresholds, active/inactive flags, exclusion lists, tier/segment checks, etc.). Do not limit this to fields literally named "eligibility" — infer intent from the condition itself.

## Naming signal — prioritize these first
Before going transformation-by-transformation, scan Tab 1 (using Excel first; only check the XML if a name/relationship is unclear in Excel) for any **Mapping or Mapplet whose name contains "Eligibility"** (case-insensitive, e.g. `m_Eligibility_Check`, `mplt_Elig_Rules`, `ELIGIBILITY_DETERMINATION`). Treat these as **high-priority targets**:
- Inspect every transformation row for these in the Excel detail tabs first. Only drill into the XML for these mapplets/mappings if the Excel logic text is missing, incomplete, or too generic to capture the actual rule — a mapping/mapplet named "Eligibility" is very likely to have its core logic spread across multiple chained transformations (e.g., a Lookup feeding an Expression feeding a Filter/Router), so if XML is needed, trace the full port-to-port flow rather than stopping at the first condition found.
- Capture these rules in full technical + plain-language detail even if the individual transformation names look generic (e.g., `EXP_TRANS1`, `FIL_1`).
- In the output table, these rows should still follow the standard format, but treat this pass as the primary source of eligibility logic — the keyword-based scan in the next section is the secondary/backstop pass to catch eligibility logic hiding in mappings that aren't named "Eligibility."

## Where to look
Eligibility logic typically appears in these transformation types — check all of them **in the Excel detail tabs first**; only consult the XML for a given transformation if its Excel logic text is missing/incomplete or its lineage needs confirming:
- **Filter transformations** – filter condition
- **Router transformations** – each group's condition
- **Expression transformations** – IIF/DECODE/CASE-like logic on output ports, especially flag/indicator ports
- **Lookup transformations** – lookup override SQL / lookup condition used to validate eligibility
- **Update Strategy** – conditional insert/update/reject logic tied to eligibility
- **Mapplets** – repeat the same checks *inside* the mapplet's internal transformations, using the Excel detail tabs for that mapplet if present; a mapplet used by multiple mappings should have its logic captured once per mapping that calls it (see Output rules below)
- **Source Qualifier** – SQL override with WHERE clause conditions, if used for eligibility filtering

## Process
1. **Start from Tab 1 (Overview)** to get the full list of Sessions → Mappings → Transformations in scope.
2. **Use Tab 2 through Tab N as the primary source** of logic text for each transformation (Session, Mapping, Transformation, Logic columns). Go through **every** detail tab in the workbook — don't stop after the first one — and merge them into a single working list. This Excel-derived list is your default; treat it as complete unless a gap is found in step 3.
3. **Check the XML only where the Excel is insufficient.** For each transformation/mapping/mapplet in your working list, check the XML **only if one of these applies**:
   - The Excel "Logic" cell is blank, truncated, or too vague to represent an actual condition (e.g., "see mapplet", "complex logic", "N/A")
   - A Mapping/Mapplet appears in Tab 1 but has no rows at all in any detail tab
   - The lineage is unclear — e.g., which mapplet a mapping actually invokes, or how a port feeds downstream — and this can't be resolved from Excel alone
   
   When one of these triggers, use the XML to pull the *complete* expression/condition text, drill into the mapplet's internal transformations, and/or confirm the transformation type. Do not open the XML for transformations where the Excel logic text is already usable — this keeps XML usage targeted to lineage tracing and gap-filling only, as intended.
4. **Filter down** to only transformations/conditions that represent eligibility logic (skip pure data movement, formatting, type conversion, or non-conditional derivations).
5. **Consolidate**: if the same mapplet/logic is reused across multiple mappings, list it under each Mapping/Mapplet that uses it (don't collapse into one row) so the output reflects where it's actually active in the workflow.
6. **De-duplicate — both row-wise and cell-wise**:
   - **Row-wise**: if the same Session + Mapping/Mapplet + Transformation + Condition combination appears more than once (e.g., pulled from more than one detail tab, or the mapplet is invoked twice with an identical condition within the same mapping), keep a single row only.
   - **Cell-wise**: within the "Eligibility Rules/Logics" summary cell (where multiple rules are concatenated as a bullet list for one Session+Mapping/Mapplet), do not repeat the same rule text twice in the same cell — compare rules after normalizing whitespace/case before adding to the bullet list, and skip any that are already present, even if pulled from a different source tab or transformation with the same underlying condition.
   - Do **not** merge rows that look similar but differ meaningfully (different Session, different condition threshold, different transformation) — only remove true duplicates, not near-duplicates that represent distinct rules.
6. **Write the rule in plain business language** in addition to the technical expression, e.g.:
   - Technical: `IIF(AGE >= 18 AND STATUS = 'ACTIVE', 'Y', 'N')`
   - Plain-language: "Member is eligible if Age ≥ 18 and Status = Active"

## Output format
Produce a new Excel tab named **"Eligibility Rules"** with these columns:

| Column | Description |
|---|---|
| Session | Session name from Tab 1/Tab 2 |
| Mapping/Mapplet | Mapping name, and if the logic originates inside a mapplet, note it as `MappingName → MappletName` |
| Transformation Name | Name of the transformation (Filter/Router/Expression/Lookup etc.) where the logic lives |
| Transformation Type | Filter / Router / Expression / Lookup / Update Strategy / Source Qualifier |
| Eligibility Rule/Logic (Technical) | Exact condition/expression as found in XML |
| Eligibility Rule/Logic (Plain Language) | Business-readable translation of the condition |
| Source (Excel/XML) | "Excel (Tab name)" if pulled as-is from a detail tab; "XML - gap fill" if the Excel logic was missing/incomplete and XML was used to complete it; "XML - lineage" if XML was only used to confirm mapping/mapplet/port relationships |

If a simplified 3-column view is also needed (per your original ask), add a second tab **"Eligibility Rules - Summary"** with just:
`Session | Mapping/Mapplet | Eligibility Rules/Logics` — where the last column concatenates all rules found for that Session+Mapping/Mapplet combination as a bullet list within the cell.

## Quality checks before finalizing
- Every mapplet found in the Excel/XML that's invoked by an in-scope mapping has been checked, not just listed by name.
- No duplicate rows for the same Session+Mapping+Transformation combination.
- No duplicate rule text within any single "Eligibility Rules/Logics" summary cell in the Summary tab — check for near-identical wording (case/whitespace differences) too, not just exact string matches.
- Every technical expression has a plain-language translation.
- Flag any transformation where the XML condition and the Excel detail-tab "Logic" text disagree, so it can be manually verified.
- Confirm no detail tab (Tab 2...Tab N) was skipped — cross-check the tab count/names used against what's actually in the workbook.
- Confirm every Mapping/Mapplet with "Eligibility" in its name has been fully covered — from Excel where available, and traced end-to-end in the XML only where Excel was missing/incomplete.
- Flag any session/mapping from Tab 1 that has **zero** eligibility logic found, so it's clear the workflow was checked, not skipped.
- Confirm XML was not used as a blanket cross-reference for every row — check that each "XML - gap fill" or "XML - lineage" row genuinely had a documented gap in Excel, not just used out of habit.

---
**Now apply the above to the attached Excel workbook and XML workflow export, and generate the output as described.**
