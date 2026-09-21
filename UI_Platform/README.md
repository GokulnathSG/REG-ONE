# Informatica Workflow Analysis & Documentation Platform

A Flask web app that ingests an Informatica PowerCenter Workflow export
(XML or the JSON-mirrored equivalent) and produces interactive lineage
visualization, an execution-ordered tabular analysis, and downloadable
technical documentation (DOCX/PDF). Implements the design in the
accompanying Software/Technical Design Document.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000 and upload an `.xml` or `.json` PowerCenter
workflow export.

## Input format

- **XML**: a standard PowerCenter Repository Manager / pmrep workflow export
  (`<POWERMART><REPOSITORY><FOLDER>...`).
- **JSON**: the same export tree serialized generically as
  `{"root": {"tag": ..., "attributes": {...}, "children": [...]}}` — i.e. a
  1:1 XML-to-JSON mirror, not a bespoke schema. If your own extraction
  pipeline (e.g. `informatica_lineage_md`) already converts XML to JSON this
  way, it will load directly.

Both formats are converted into the same generic `{tag, attributes,
children}` tree (see `app/parsers/tree_utils.py` for the XML→tree step) and
then parsed by the single shared `app/parsers/tree_parser.py`, so parsing
logic only needs to be maintained in one place.

## Project layout

```
app/
  routes/        Flask blueprints (Presentation layer)
  services/       Orchestration (Service layer)
  parsers/        XML/JSON -> generic tree -> domain model
  analyzer/        Execution ordering, table rows, lineage chains
  graph/           NetworkX graph construction + PyVis HTML export
  generators/       DOCX (python-docx) and PDF (ReportLab) report builders
  models/          Domain classes: Workflow, Session, Mapping, Mapplet,
                    Transformation, Table, Field
  templates/        Jinja2 templates (Bootstrap 5, no JS framework)
  static/           css/, js/, graphs/ (generated PyVis HTML, gitignored)
  uploads/          Temporary uploaded files (gitignored)
  reports/          Generated DOCX/PDF output (gitignored)
config.py
app.py             App factory + entrypoint
requirements.txt
```

## What's implemented

- **Module 1 - Visualization**: upload page; Overview tab (session graph,
  zoom/pan/auto-layout, click-to-open session detail panel); Table View tab
  (execution-ordered rows, Mapplet column only shown when mapplets are
  present); Mapping drill-down page (transformation graph + Back button,
  click-to-open transformation detail panel).
- **Module 2 - Implementation**: single downloadable "Overview Workflow"
  DOCX containing Session / Mapping / Table / Transformation tabs (each with
  Previous/Next context) plus the Mapping Transformation Lineage table.
- **Module 3 - Printable Report**: DOCX and PDF for Workflow Summary,
  Technical Documentation, Implementation Documentation, Transformation
  Lineage, Mapping Documentation, Session Documentation, Data Lineage
  Report, Graph Images (static PNG via matplotlib, since PyVis output is
  HTML/JS-only), and Table Summary.
- **REST-ish endpoints**: `/upload`, `/workflow`, `/table-view`, `/graph`,
  `/mapping/<name>`, `/session/<name>`, `/transformation/<name>`,
  `/implementation`, `/reports`, `/report/docx`, `/report/pdf`, `/healthz`.
- **Error handling**: invalid/corrupt XML or JSON, missing mapping
  references, circular workflow dependencies (falls back to declaration
  order with a warning), oversized uploads (413), unknown report sections
  (400) — see `app/services/workflow_service.py` and the analyzer's
  structural warnings.

## Notes and known simplifications (see TDD Section 11 - Future Enhancements)

- Single in-memory cache of the most recently uploaded workflow (no DB, no
  multi-user session isolation) — matches the "no database" constraint in
  the design document. Swap `app/services/workflow_service.py`'s `_CACHE`
  for a session- or DB-backed store if concurrent multi-user use is needed.
- `MAX_CONTENT_LENGTH` in `config.py` defaults to 100 MB to comfortably fit
  large real-world exports (the reference sample used during development
  was ~57 MB / 1,072 transformations); tune per environment.
- Business-logic summaries on the Transformation detail panel are generated
  by deterministic, per-transformation-type rules from structural metadata
  already in the export (see `_business_logic_for` in
  `app/parsers/tree_parser.py`) — no LLM inference is used, consistent with
  the design document's scaling principle of keeping structural lineage
  deterministic.
- The Overview Workflow DOCX iterates every transformation in the workflow;
  for very large workflows (1,000+ transformations) this can take on the
  order of ~15 seconds — acceptable for an on-demand download, but a
  candidate for background generation if it becomes a bottleneck.
