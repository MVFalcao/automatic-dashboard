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

The backend requires Python 3.11 or newer. The frontend requires Node.js 24 or
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

Use the exact Node version in `.nvmrc` (`24.18.0`). `npm ci` is preferred in CI
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
server support includes a pinned `aiohttp==3.13.3` adapter dependency.
Provider API keys and app secrets are represented by opaque OS-keyring
references; native OAuth flows (including Codex device-code login) remain in
Hermes/provider protected stores. Provider routing selects the lowest estimated
total input/output token count, honors an explicitly selected provider, and
raises a confirmation-required error rather than silently falling back after
failure.
Structured responses are validated before use, and the optional local memory
file stores only compact preferences, approved terminology/layout, and feedback
after confidential-value filtering. Install the optional `keyring` package on
the target OS to enable its credential backend.

The local setup API exposes provider setup/status at `/api/providers` and
`/api/hermes/status`; raw secrets are rejected by the strict request models.
The synthetic review screen allows Gemini, Claude, or DeepSeek API-key setup
before a project exists, so Hermes revision is never presented as available
without an in-app provider path. The key is written directly to the operating
system credential store, only a secret-free provider reference is retained,
and the managed Hermes gateway is restarted with the selected credential in
child-process memory. Provider transport failures are reported as recoverable
provider errors rather than invalid dashboard drafts.
The browser opens on a project home screen rather than immediately starting a
new intake. It lists the local registry, provides an explicit **Create new
project** action, and reopens an existing project's checksum-verified active
specification and operations without copying project data into the application
installation.
The gateway follows Hermes' documented localhost API server configuration:
<https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server/>.

## Local installation and release checks

Linux users can install into a user-owned directory without Docker or
administrator access:

```bash
bash scripts/install-linux.sh
"${XDG_DATA_HOME:-$HOME/.local/share}/universal-dashboard-agent/bin/dashboard-first-run"
"${XDG_DATA_HOME:-$HOME/.local/share}/universal-dashboard-agent/bin/dashboard-start"
```

Windows users run `scripts/install-windows.ps1` in PowerShell. Both installers
check Python 3.11+, Node.js 24+, install the web dependencies and Playwright
Chromium, create an application-owned Hermes environment pinned to
`hermes-agent==0.13.0`, and generate launchers. They never copy the ignored
private source sample. The first-run command prints provider login and model
selection guidance but never asks for or writes a provider secret. Provider
keys remain in the OS credential store and native OAuth tokens remain in
Hermes/provider stores.

Every launch is loopback-only (`127.0.0.1`), uses a narrow web-origin CORS list,
and enables local bearer authentication. The launcher creates that bearer token
in process memory for the session; it is not written to project configuration.
The generated `config/local.env` contains only non-secret host and port values.
On Windows, the launcher recovers from a partial prior shutdown by stopping only
stale processes whose executable belongs to the application installation. It
never terminates an unrelated process using the same port. Startup output is
written to `logs/api.stdout.log`, `logs/api.stderr.log`, `logs/web.stdout.log`,
and `logs/web.stderr.log` inside the application directory for troubleshooting.
Read-only diagnostics are available with `python -m
automation.release.diagnostics --json`. Release smoke tests are provided by
`scripts/smoke-test-install.sh` and `scripts/smoke-test-install.ps1`.
The browser UI also exposes sanitized component diagnostics. `GET
/api/diagnostics` returns value-free health information, while `POST
/api/diagnostics/support-bundle` downloads a ZIP containing runtime versions,
health checks, and redacted operational events. It excludes credentials,
prompts, subprocess output, project paths, source values, and report content.

Uninstall requires an explicit app directory and confirmation. These commands
remove only the application-managed directory and never select project folders
automatically.

The frontend proxies `/backend/*` to the FastAPI service at `127.0.0.1:8000`, so
the browser does not require a network-exposed API.

JSON API onboarding is available at `/api/api-sources`. `POST /inspect` accepts
either a representative JSON response or an OpenAPI/Swagger document and
returns inferred fields, business-language mapping explanations, and review
issues without retaining sample values. `PUT /{source_id}` stores only the
secret-free source definition. `POST /sync` performs an authenticated JSON-only
full or confirmed incremental refresh with bounded retries, rate limiting,
cursor/page/link pagination, deterministic flattening/mapping, extraction
provenance, and schema-drift classification. API keys and bearer tokens are
looked up through credential references; OAuth tokens remain in the Hermes or
provider protected store.

Local schedules are available at `/api/schedules`. A schedule can use a daily,
weekly, monthly, or five-field cron preset and includes a timezone-aware preview
before activation. Activation requires explicit confirmation that both the
project and its source data are non-confidential. Schedule, run, and artifact
metadata are stored in SQLite; generated reports are written only to the
selected local folder. Failed runs remain in history and never replace the
latest successful report set. Successful report sets retain ten versions by
default, configurable per schedule.

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

## Windows v0.2.0 release candidate

The supported first public distribution is a per-user, offline Windows x64
Setup.exe. It includes the application runtimes and does not require Python,
Node.js, or internet access during installation. The unsigned installer may
show a Windows SmartScreen warning; verify its SHA-256 value against the
published `SHA256SUMS.txt` before choosing **More info → Run anyway**.

After installation, open **Universal Dashboard Agent** from the Start Menu.
The local browser UI is bound to `127.0.0.1` only. In Project operations, use
**Connect Codex** to complete the browser device login, or configure Claude,
Gemini, or DeepSeek with an API key stored in the operating system credential
manager. OAuth tokens never enter project files or the browser UI.

The installer also creates **Configure AI provider** and **Uninstall Universal
Dashboard Agent** shortcuts. Uninstall removes only the application directory;
project folders and report folders elsewhere are not selected automatically.
An in-place upgrade stages the previous installation as a temporary backup,
preserves configuration, the local project registry, and Hermes authentication
state, and restores the previous installation if the upgrade fails.

Release maintainers first run the `draft-release` workflow manually in
`dry-run` mode. A `v0.2.0` tag from `main`, or an explicitly selected manual
`draft` run, builds and tests a draft GitHub Release containing only the
Setup.exe, checksums, and release manifest. Workflow artifacts retain the same
candidate plus sanitized diagnostics for 14 days. A maintainer must complete
the clean-machine checklist in `final_implementation_v2.md` and explicitly
publish the draft; no workflow publishes a public release automatically. See
`RELEASE_RUNBOOK.md` for the complete maintainer sequence.
