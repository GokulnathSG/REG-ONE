
Create a Word document from the provided field-level specification document.

For each field, replace the existing Lineage Chain section with a simple medium-sized flowchart image.

FLOWCHART STYLE REQUIREMENTS:
- Use a clean dark theme flowchart style.
- Use dark rectangular process boxes for normal steps.
- Use dark diamond decision nodes for conditional logic.
- Add a small “Start” node at the beginning of every flowchart.
- Use light-colored connector arrows between shapes.
- Use “Yes” / “No” labels on conditional paths wherever a decision node is used.
- Keep each field’s flowchart separate. Do not combine fields.
- Keep the overall diagram simple and medium-sized.
- Do not overcrowd the diagram.
- Ensure all text stays inside the shape boundaries.
- Wrap long labels automatically inside shapes.
- Shorten labels into plain business English where needed.
- Avoid very long technical expressions inside shapes.
- Use concise labels, preferably 2–4 lines per shape.
- If logic is complex, summarize the condition in business terms rather than copying the full formula.
- Use readable font size and adequate shape padding.
- Maintain sufficient spacing between shapes and arrows.
- Avoid overlapping shapes, labels, and connector lines.

LABEL CLEANING RULES:
- Remove technical prefixes from all labels, including:
  EXP_, SRT_, RTR_, LKP_, AGG_, JNR_, SQ_, UPD_, TGT_
- Remove similar object-type prefixes where applicable.
- Use only meaningful business or field names.
- Do not use these words anywhere in flowchart labels:
  transformation, expression transformation, source qualifier,
  router, lookup transformation, aggregator, joiner,
  update strategy, mapping, session, workflow, pipeline,
  informatica, ETL, sorter

LINEAGE PARSING RULES:
- Parse each numbered step in the Lineage Chain and Lineage dependancy Branches.
- Include only meaningful derivation, condition, lookup, formula, hardcoded assignment, or business-rule steps.
- usage of Table_name.field_name and their respective logics are permitted.
- Exclude direct pass-through steps.
- Exclude rename-only steps.
- Exclude steps where a field is copied unchanged with no logic.
- Convert technical formulas such as IIF, DECODE, CASE, WHEN, lookup logic, filter logic, or calculations into plain business English.
- If the field is hardcoded, show a simple flow:
  Start → Set fixed value → Populate target field
- If the field has conditional logic, use:
  Start → Read source/input → Decision diamond → Yes/No branches → Populate target field
- If the field has multiple validations, keep the flow high-level and simple.


DOCUMENT STRUCTURE REQUIREMENTS:
- Preserve the original document structure and field order.
- Before processing fields, scan the entire document and list all field names in sequence:
  Field 1, Field 2, Field 3, … Field N.
- For every field, output sections in this order:
  1. All original subsections except Lineage Chain, unchanged
  2. Lineage Chain heading with the generated flowchart image
  3. Add a new section: “### Field Extraction Logic”
  4. Add a horizontal divider line after each field
- Do not skip any field.
- Do not merge fields.
- Do not add commentary outside the document content.

OUTPUT:
- Generate the final result as a Word document (.docx).
- Embed one flowchart image per field.
- Ensure every flowchart is clean, readable, and visually consistent with:
  always give little space between the shapes and connector (arrow) should be visible enough. 
  white background with vertical orientation,
  dark process boxes (only shape),
  dark decision diamonds,
  Start node,
  light connector arrows,
  Yes/No labels on conditional paths.