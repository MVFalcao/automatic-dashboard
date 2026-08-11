# Universal Dashboard Agent — Implementation Plan

## 1. Product vision

Build a generic Hermes-powered agent that helps a nontechnical user create an
automated dashboard from:

1. A dashboard or report sample.
2. An API or API documentation.
3. A short conversation describing the desired result.

The agent analyzes the sample, infers a reusable dashboard schema, maps the API
data to that schema, asks only the questions it cannot answer safely, and produces
a preview consisting of a web dashboard, an Excel report, and a PDF report. The
user can request changes in natural language and explicitly approve a version
before it becomes active.

The system must work for different industries and dashboard types. Concepts from
one sample—such as candidates, sales, orders, projects, statuses, or teams—must
never be hard-coded into the core platform.

## 2. Core principles

- Keep the experience understandable for nontechnical users.
- Ask one short question at a time.
- Use the user's language and locale throughout the experience.
- Infer information from supplied materials before asking the user.
- Explain business decisions without API or schema jargon.
- Recommend a sensible default when clarification is needed.
- Generate tangible previews before requesting approval.
- Use one versioned specification for the web, Excel, and PDF outputs.
- Use deterministic code for authoritative calculations.
- Use Hermes for discovery, orchestration, interpretation, and recommendations.
- Never allow model-generated narrative to overwrite calculated metrics.
- Keep credentials and personal data out of logs and public examples.
- Preserve the last approved version while a revision is under review.
- Never activate schedules or external delivery without explicit approval.

## 3. Target workflow

```text
Simple guided conversation
          +
API connection or documentation
          +
Dashboard/report sample
          |
          v
Hermes discovery and schema inference
          |
          v
Clarifying questions, only when necessary
          |
          v
Plain-language confirmation summary
          |
          v
Versioned draft dashboard specification
          |
          v
Synthetic preview package
  - interactive web dashboard
  - example Excel report
  - example PDF report
          |
          v
User approves, rejects, or requests changes
          |
          v
Approved deterministic reporting pipeline
          |
          v
Scheduled API analysis and report generation
```

## 4. Responsibility boundaries

### Hermes responsibilities

- Conduct the guided requirements conversation.
- Detect and confirm the user's language.
- Analyze Excel, PDF, CSV, JSON, screenshots, and existing dashboard samples.
- Inspect API documentation and representative responses.
- Infer fields, dimensions, metrics, filters, layouts, and report sections.
- Suggest mappings between API data and the inferred dashboard concepts.
- Identify ambiguity and ask business-friendly clarification questions.
- Generate and revise the draft dashboard specification.
- Explain data-quality findings and calculated results.
- Generate structured insights, risks, and recommended actions.
- Coordinate preview and report generation tools.
- Detect changes that may require schema rediscovery.

### Deterministic application responsibilities

- Authenticate with APIs.
- Fetch, paginate, retry, cache, and normalize source data.
- Validate schemas and mappings.
- Calculate all authoritative metrics.
- Apply filters, grouping, comparisons, and time periods.
- Detect missing, invalid, and duplicate data.
- Render the web dashboard from the approved specification.
- Generate Excel and PDF artifacts.
- Apply localization formats and approved terminology.
- Enforce privacy, approval, versioning, and audit rules.
- Schedule production runs and store their artifacts.

## 5. Step-by-step delivery plan

### Step 1 — Complete the project context

Populate `context.md` with initial platform rules:

- Product purpose and target users.
- Supported sample formats.
- Supported API authentication methods.
- Supported output formats.
- Privacy and retention requirements.
- Approval and publishing rules.
- Default languages and locales.
- Deployment and report-delivery expectations.

Create `.hermes.md` later during implementation so Hermes automatically loads a
short bootstrap that requires it to read `context.md`. Keep `context.md` as the
user-maintained source of product and business rules.

Acceptance criteria:

- Missing rules are listed explicitly.
- Conflicting rules have a defined priority.
- Hermes does not invent a business rule when the context is incomplete.

### Step 2 — Define the guided intake conversation

Implement a stateful intake flow that asks one question at a time:

1. Confirm the interaction and report language.
2. Ask what decision the dashboard should support.
3. Ask who will use it.
4. Ask where the data currently lives.
5. Collect API documentation, connection information, or a sample response.
6. Collect an existing report or dashboard sample when available.
7. Ask how often the information should update.
8. Ask which outputs are required: web, Excel, PDF, or a combination.
9. Ask where reports should be available or delivered.
10. Present a plain-language summary for confirmation.

The agent must not ask a question whose answer can be safely inferred from the
uploaded sample, API documentation, `context.md`, or an earlier answer.

Acceptance criteria:

- Every question can be understood without technical knowledge.
- Technical ambiguity is translated into a business decision.
- Each difficult choice includes a recommendation and simple examples.
- The user can correct any earlier answer in natural language.
- External delivery remains disabled until explicitly approved.

### Step 3 — Implement localization and terminology

Store language and locale separately:

```yaml
localization:
  interaction_language: pt-BR
  dashboard_language: pt-BR
  report_languages: [pt-BR]
  timezone: America/Sao_Paulo
  currency: BRL
  date_format: DD/MM/YYYY
  number_format: "1.234,56"
  week_starts_on: monday
```

Support:

- Localized conversations, UI labels, filters, errors, and notifications.
- Localized Excel sheets and headings.
- Localized PDF content.
- Local dates, numbers, percentages, currencies, and timezones.
- An approved glossary mapping internal concepts to display terminology.
- One dashboard language, switchable languages, or separate localized exports.

Do not translate source field names, identifiers, API keys, names, or the source
values required for API filters. Store source values separately from display
labels.

Acceptance criteria:

- Metrics remain identical across report languages.
- User-approved terminology is consistent in all outputs.
- Ambiguous translations require review.
- Privacy detection works across all supported languages.

### Step 4 — Build the sample-analysis subsystem

Create parsers for:

- Excel workbooks.
- PDF reports.
- CSV files.
- JSON exports.
- Dashboard screenshots or images.
- Existing dashboard URLs when authorized.

Extract, when available:

- Sections, cards, tables, charts, filters, and navigation.
- Sheet names, headers, formulas, validations, styles, and relationships.
- Metrics, dimensions, statuses, categories, owners, and time periods.
- Visual hierarchy and formatting conventions.
- Sensitive fields and potential personal data.
- Unclear or contradictory calculations.

Use the current workbook only as the first design reference. The core schema must
not depend on its candidate-management terminology or fixed formulas.

Acceptance criteria:

- Analysis produces a structured sample manifest.
- Every inferred element records its evidence and confidence.
- Unsupported or unreadable elements are reported rather than invented.
- Source samples are treated as read-only.

### Step 5 — Build the API discovery and adapter layer

Support:

- OpenAPI/Swagger documents.
- Documentation URLs.
- Representative JSON responses.
- REST endpoints without formal documentation.
- Bearer token, API key, OAuth, and configurable authentication.
- Cursor, page-number, and link-based pagination.
- Timeouts, bounded retries, and rate limits.
- Full and incremental synchronization.

Define a generic source adapter interface so new systems can be added without
changing the reporting engine.

Acceptance criteria:

- Secrets never enter version control or ordinary logs.
- API responses are validated before use.
- Pagination and partial failures are tested.
- Each extraction records its source, time, and status.
- Development can run against local mock API fixtures.

### Step 6 — Define the canonical data model

Create versioned schemas for:

- Source definition.
- Normalized record.
- Dimension and category.
- Metric and metric series.
- Filter and reporting period.
- Visualization.
- Data-quality issue.
- Agent insight and recommendation.
- Report metadata and artifact.
- Localization glossary.

The canonical model must support arbitrary business domains and allow source
fields to be mapped through configuration.

Acceptance criteria:

- All schemas are machine validated.
- Schema migrations are versioned.
- Unknown fields do not silently change calculations.
- Sensitive fields are explicitly classified.

### Step 7 — Implement schema inference and API mapping

Hermes combines the sample manifest and API description to propose:

- Dashboard sections and layout.
- Canonical fields and their types.
- API-to-canonical mappings.
- Dimensions and filters.
- Metric definitions.
- Visualization choices.
- Excel and PDF sections.
- Privacy classifications.
- Localization terminology.

For every proposal, retain:

- Evidence from the sample or API.
- Confidence level.
- Assumptions.
- Unmapped sample concepts.
- Unused API fields.
- Ambiguities requiring user input.

Acceptance criteria:

- Hermes emits structured data validated against a schema.
- Low-confidence business decisions are not activated automatically.
- The user sees business explanations instead of JSONPath/schema terminology.
- Rejected mappings can be corrected without restarting discovery.

### Step 8 — Generate the dashboard specification

Produce a versioned `dashboard-spec.yaml` containing:

- Dashboard identity and layout.
- Source adapter and field mappings.
- Dimensions, filters, and metrics.
- Visualization definitions.
- Localization and glossary.
- Excel and PDF sections.
- Privacy and masking policies.
- Schedule and delivery settings.
- Approval state and version metadata.

The specification is the single source of truth for every output. Technical users
may inspect it in an advanced view, but ordinary users should not need to edit it.

Acceptance criteria:

- One specification drives web, Excel, and PDF generation.
- Invalid specifications cannot reach preview or production.
- Every change creates a new immutable version.
- The last approved version remains active during revisions.

### Step 9 — Implement deterministic metrics and data quality

Build an execution engine for configurable operations:

- Counts, sums, averages, minima, and maxima.
- Ratios and percentages.
- Filtered and grouped aggregations.
- Time buckets and period-over-period comparisons.
- Funnels and status transitions.
- Top/bottom rankings.
- Missing, invalid, duplicate, and stale-record checks.

Hermes may propose metric definitions, but the engine executes the approved
definitions. The preview must expose every KPI formula in plain language.

Acceptance criteria:

- Metrics are reproducible from the same source data and specification.
- Divide-by-zero and empty datasets are handled explicitly.
- Tests use fixed input and expected results.
- Hermes cannot change metric values through narrative output.

### Step 10 — Build synthetic preview generation

Before approval, create a complete preview package from the draft specification:

- Interactive web dashboard preview.
- Example Excel report.
- Example PDF report.
- Plain-language metric definitions.
- Assumptions and unresolved warnings.
- Summary of excluded sensitive information.

Use synthetic data by default. Synthetic records must preserve relevant types and
representative distributions without reproducing real identities or rare,
identifying combinations.

Allow a private-data preview only when explicitly authorized. Private previews
must use protected storage, masking, access logging, and automatic expiration.

Acceptance criteria:

- All three previews come from the same draft specification.
- Synthetic previews pass the privacy scanner.
- Draft previews cannot overwrite approved production artifacts.
- Preview failures return understandable corrective guidance.

### Step 11 — Implement preview-based approval

Use the following lifecycle:

```text
draft
  -> preview_generated
  -> under_review
       -> revision_requested -> new draft
       -> rejected
       -> approved -> active
```

The review experience provides:

- Visual dashboard preview.
- Excel and PDF downloads.
- Simple explanations of KPIs.
- Warnings and assumptions.
- Approve, request changes, reject, restart, and advanced-details actions.

Support natural-language changes such as:

- “Compare this month with last month.”
- “Remove the owner table.”
- “Make the status chart larger.”
- “Put the summary on the first PDF page.”

Hermes translates feedback into a new draft, validates it, and regenerates the
affected previews. Production changes only after approval.

Acceptance criteria:

- Approval records who approved which version and when.
- Feedback and generated artifacts remain linked to their version.
- No draft can be scheduled or delivered as a production report.
- Rollback to an earlier approved version is possible.

### Step 12 — Build the web dashboard renderer

Recommended initial stack:

- FastAPI backend.
- React/Next.js frontend.
- PostgreSQL for projects, specifications, runs, and metadata.
- Object storage for generated artifacts.
- Background workers for ingestion and report generation.

Render dynamically from `dashboard-spec.yaml`:

- Metric cards.
- Tables.
- Bar, line, area, pie/donut, and funnel charts.
- Date and category filters.
- Data-quality notices.
- Hermes summary, risks, and recommended actions.
- Report history and downloads.

Acceptance criteria:

- No business-specific field is required by the UI.
- Layout works on desktop and mobile.
- Filters produce the same results as exports.
- Accessibility labels follow the selected language.

### Step 13 — Build the Excel renderer

Generate Excel workbooks dynamically from the approved specification using
`openpyxl` or `xlsxwriter`.

Support:

- Summary and KPI sheets.
- Configurable dimension and detail sheets.
- Data-quality and methodology sheets.
- Hermes insights and recommendations.
- Excel tables, charts, filters, frozen panes, and formatting.
- Localized sheet names and values.
- Report period, source timestamp, and schema version.

Prefer generated tables and computed values over thousands of copied formulas.

Acceptance criteria:

- Excel totals match the web dashboard and PDF.
- Workbook generation works with no desktop Excel installation.
- Sheet names and formulas are valid in all configured locales.
- Sensitive detail sheets follow the approved privacy policy.

### Step 14 — Build the PDF renderer

Generate PDF from an HTML/Jinja template using WeasyPrint or Playwright.

Support:

- Cover and reporting period.
- Executive summary.
- KPI cards.
- Charts and tables.
- Data-quality statement.
- Risks and recommended actions.
- Methodology appendix.
- Localized typography, dates, numbers, and page labels.

Acceptance criteria:

- PDF metrics match the web and Excel outputs.
- Pages render without clipped content.
- Charts remain readable in print.
- Missing sections are omitted cleanly.

### Step 15 — Add Hermes structured analysis

After deterministic calculation, provide Hermes with:

- Approved context and terminology.
- Aggregated metrics.
- Period comparisons.
- Data-quality findings.
- A minimal anonymized sample only when necessary.

Require structured output containing:

- Executive summary.
- Material highlights.
- Risks and anomalies.
- Hypotheses clearly labeled as hypotheses.
- Recommended actions.
- Data limitations.

Acceptance criteria:

- Agent output validates before publication.
- Claims reference supplied metrics or quality findings.
- Failed analysis does not block deterministic report generation unless required.
- Raw sensitive fields are excluded from prompts by default.

### Step 16 — Sanitize the public Excel example

Do not publish the current workbook by deleting only personal and enterprise
names. Create a synthetic copy that preserves the design intent while removing:

- Personal names.
- Enterprise and program names.
- Emails, phone numbers, IDs, and contact details.
- Free-text comments.
- Person-specific sheet names and formula references.
- Document author and company metadata.
- Comments, external links, hidden values, and cached personal data.
- Rare combinations that could identify a person.

Replace them with generic values such as `Example Organization`, `Person 001`, and
`Team A`. Scan the internal XLSX ZIP/XML content for original sensitive values
before approving the file for GitHub.

Acceptance criteria:

- The source workbook is never modified.
- The public workbook uses fully synthetic records.
- A privacy test scans cell values, formulas, metadata, relationships, and XML.
- Only the sanitized copy may exist under `examples/`.

### Step 17 — Add scheduling and production runs

An approved production run performs:

1. Fetch API data.
2. Validate and normalize records.
3. Calculate metrics and quality findings.
4. Compare with earlier periods.
5. Request structured Hermes interpretation.
6. Validate agent output.
7. Generate web data, Excel, and PDF.
8. Store the run and artifacts.
9. Publish or deliver only approved outputs.
10. Notify on failure or configured anomalies.

Use Hermes cron or an external scheduler with bounded retries, hard stops, and
idempotent run identifiers.

Acceptance criteria:

- Re-running the same job does not create conflicting reports.
- Failures never replace the last successful report.
- External delivery is auditable and explicitly authorized.
- Logs redact credentials and sensitive values.

### Step 18 — Implement schema-drift handling

Detect when:

- API fields disappear or change type.
- New statuses or categories appear.
- Required mappings become invalid.
- Sample or business requirements change.

Classify drift as:

- Safe: accept without affecting approved calculations.
- Review required: create a new draft and preview.
- Blocking: stop publication while preserving the last successful report.

Acceptance criteria:

- Production specifications never mutate silently.
- Users receive a plain-language explanation of the change.
- Revised mappings follow the normal preview and approval lifecycle.

### Step 19 — Test, secure, and observe the platform

Test:

- Intake state and language switching.
- Sample parsing.
- API pagination, retries, and authentication failures.
- Schema inference validation.
- Metric correctness.
- Localization consistency.
- Privacy and synthetic-data generation.
- Web, Excel, and PDF parity.
- Approval and rollback behavior.
- Malformed Hermes output.
- Empty, partial, duplicated, and high-volume datasets.
- Schema drift and failed scheduled runs.

Add:

- Structured, redacted logs.
- Run status and duration metrics.
- API freshness monitoring.
- Report-generation alerts.
- Audit history for approvals and deliveries.
- Cost and token monitoring for Hermes operations.

## 6. Proposed repository structure

```text
automatic-dashboard/
├── .hermes.md
├── AGENTS.md
├── context.md
├── IMPLEMENTATION_PLAN.md
├── automation/
│   ├── adapters/
│   ├── discovery/
│   ├── normalization/
│   ├── metrics/
│   ├── agent/
│   ├── reports/
│   ├── privacy/
│   └── pipeline/
├── config/
│   ├── schemas/
│   ├── sources/
│   └── reports/
├── dashboard/
│   ├── api/
│   └── web/
├── examples/
│   ├── dashboard_example.xlsx
│   ├── sample-api-response.json
│   ├── dashboard-spec.yaml
│   ├── expected-report.xlsx
│   └── expected-report.pdf
├── templates/
│   ├── excel/
│   └── pdf/
├── tests/
│   ├── fixtures/
│   ├── integration/
│   └── privacy/
└── data/
```

## 7. Suggested implementation milestones

### Milestone 1 — Discovery prototype

- Complete `context.md`.
- Add Hermes bootstrap instructions.
- Implement the guided intake state model.
- Analyze Excel and JSON samples.
- Produce a structured sample manifest.
- Infer and validate a draft dashboard specification.

### Milestone 2 — Preview prototype

- Implement mock API ingestion.
- Add the deterministic metric engine.
- Generate synthetic preview data.
- Render a basic web dashboard.
- Generate matching Excel and PDF previews.
- Implement revision and approval states.

### Milestone 3 — Generic API reporting

- Add production API adapters and secret handling.
- Implement source-to-canonical mappings.
- Add data-quality checks and schema drift detection.
- Add structured Hermes insights.
- Verify parity among web, Excel, and PDF outputs.

### Milestone 4 — Production platform

- Add users, projects, permissions, and audit history.
- Add storage, scheduling, and report delivery.
- Add multilingual UI and report variants.
- Add monitoring, retry controls, and rollback.
- Complete security, privacy, load, and failure testing.

### Milestone 5 — Public GitHub release

- Generate the fully synthetic workbook example.
- Run workbook and repository privacy scans.
- Add mock API fixtures and expected reports.
- Add setup, architecture, and contribution documentation.
- Confirm that no credentials, real identities, or enterprise names remain.

## 8. Definition of done

The initial product is complete when a nontechnical user can:

1. Start in their preferred language.
2. Explain the desired outcome in ordinary language.
3. Connect or describe an API.
4. Upload a dashboard/report sample.
5. Answer only necessary business questions.
6. Confirm a plain-language requirements summary.
7. Review a synthetic web, Excel, and PDF preview.
8. Request changes conversationally.
9. Approve a version.
10. Receive reproducible reports generated from API data.

The same approved specification must produce consistent metrics in every output,
and the system must remain generic enough to repeat this process for a different
dashboard domain without changing core application code.
