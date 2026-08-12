# Automatic Dashboard

Planning scaffold for a generic, Hermes-powered dashboard generation platform.

## Structure

- `dashboard/` — web interface and application API
- `automation/` — discovery, API adapters, metrics, reporting, and pipelines
- `config/` — source, report, and schema configuration
- `data/` — local data inputs and generated outputs
- `scripts/` — development and deployment utilities
- `tests/` — automated tests
- `examples/` — synthetic samples safe for public documentation
- `templates/` — Excel and PDF report templates
- `reports/` — generated local report artifacts

Empty folders contain a `.gitkeep` file so Git can track them. Remove those files when adding real project files.

## Project guidance

- `IMPLEMENTATION_PLAN.md` contains the complete delivery roadmap.
- `context.md` will contain user-maintained product and business rules.
- `.hermes.md` and `AGENTS.md` define agent and repository conventions.

## Development

The backend requires Python 3.11 or newer. The frontend requires Node.js 20.9 or
newer. End users will not need to perform these development steps after the
Windows installer and Linux setup script are implemented.

Backend:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
uvicorn dashboard.api.main:app --host 127.0.0.1 --port 8000
```

Alternatively, with `uv` installed, `uv sync --extra dev --locked` recreates the
hash-locked environment recorded in `uv.lock`.

Frontend:

```bash
cd dashboard/web
npm install
npm run dev
```

Use the Node version in `.nvmrc` (20.9.0 or newer). `npm ci` is preferred in CI
and clean environments because it installs exactly from `package-lock.json`.

Both services bind to the local computer only.

The current guided setup implementation:

- asks one English or Portuguese question at a time;
- keeps intake sessions in process memory rather than storing conversation transcripts;
- accepts XLSX, PDF, PNG, JPEG, and SVG reference uploads;
- validates file content against its extension; and
- deletes each temporary reference upload immediately after inspection.

Reference discovery currently produces:

- structural Excel evidence including sheets, formulas, merged ranges, charts, and field candidates;
- PDF page geometry and optional text-line counts;
- raster-image dimensions and safe SVG structure metadata;
- a format-neutral manifest that excludes source record values; and
- an explicitly unapproved draft schema showing proposed sections and fields.

Field labels and type inference are included only when the user permits data
extraction. The discovery layer does not infer or activate KPI formulas.

Section approval supports explicit dependencies: rejecting a section blocks only
its dependents, while independent sections may continue. Activation is allowed
only when every section is approved and the user confirms the schema contains no
confidential information. Approved schemas are then stored as immutable numbered
YAML or JSON versions in the user-selected project folder.

Synthetic preview generation renders the same deterministic invented records into
the user-selected web, Excel, and PDF formats. Synthetic emails use the reserved
`example.invalid` domain, every artifact contains a synthetic-data notice, and the
preview endpoint requires the caller to choose the record count and output formats.

Population inspection accepts a local CSV/XLSX file or folder, reports structural
issues and likely confidential columns without exposing record values, and proposes
schema mappings for approval. Applying an import requires explicit mode and mapping
approval; update mode additionally requires a confirmed identifier. Confidential
imports cannot be marked for persistence.

The deterministic metric engine supports approved counts, sums, averages, ratios,
filters, groupings, rankings, period comparisons, and data-quality checks. Draft or
unapproved metric definitions cannot execute.

An approved `DashboardSpec` is the canonical source for web, Excel, and PDF output.
It validates fields, mappings, metrics, filters, visualizations, section dependencies,
layout, localization, privacy, and selected outputs as one strict contract. Approved
versions store the generated structure as immutable JSON and compact approval metadata
as YAML; checksums detect edits, and rollback moves only the active-version pointer.

After guided intake, the local web interface opens a bilingual synthetic review
workspace with KPI cards, tables, and ECharts visualizations. Users can approve or
request revisions by section and directly change the accent color, chart type, and
section order. The canonical render API recalculates synthetic metrics deterministically;
confidential specifications require explicit authorization and are returned for
temporary in-memory display only.

Excel and PDF reports consume the same validated `ReportDocument` used by the web
output. Excel is generated with `openpyxl`; PDF is printed from the shared report
HTML/CSS using Playwright Chromium. Confidential generation requires lifecycle
approval, returns one-time download artifacts, and deletes the temporary file as
soon as its bytes are transferred to the download response.

The managed Hermes integration keeps its runtime in an application-owned
environment pinned to `hermes-agent==0.13.0`. Its authenticated gateway is bound
to `127.0.0.1` only and uses the documented `API_SERVER_KEY` bearer flow. API
keys and app secrets are represented by opaque OS-keyring references; native
OAuth flows (including Codex device-code login) remain in Hermes/provider
protected stores. Provider routing selects the lowest estimated total
input/output token count, honors an explicitly selected provider, and raises a
confirmation-required error rather than silently falling back after failure.
Structured responses are validated before use, and the optional local memory
file stores only compact preferences, approved terminology/layout, and feedback
after confidential-value filtering. Install the optional `keyring` package on
the target OS to enable its credential backend.

The local setup API exposes provider setup/status at `/api/providers` and
`/api/hermes/status`; raw secrets are rejected by the strict request models.
The gateway follows Hermes' documented localhost API server configuration:
<https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server/>.

The frontend proxies `/backend/*` to the FastAPI service at `127.0.0.1:8000`, so
the browser does not require a network-exposed API.

Checks:

```bash
pytest -q
cd dashboard/web
npm run check
npm run build
npm audit --omit=dev
```

The original workbook is private and ignored by Git. The publishable synthetic
version is generated with:

```bash
python3 -m pip install -r requirements-dev.txt
python3 scripts/sanitize_excel_sample.py \
  private_source_dashboard.xlsx \
  examples/dashboard_example.xlsx \
  --replace 'PRIVATE_BRAND=Example Organization' \
  --forbidden-term 'PRIVATE_BRAND'
```

The sanitizer automatically discovers person-specific team labels. Supply one
`--replace` and `--forbidden-term` pair for each additional private organization,
program, or person label found in a source template.

## Next step

Complete the platform rules in `context.md`, then begin Milestone 1 in
`IMPLEMENTATION_PLAN.md`.
