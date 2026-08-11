# Universal Dashboard Agent — Product Context

## Confirmed requirements

### Interaction languages

- Initially support English and Portuguese.
- Detect the language currently used by the user and respond in that language.
- Do not display both languages together unless the user explicitly requests it.

### Dashboard and report language

- Use the language of the conversation in which the dashboard project was created.
- Apply that language to the web dashboard, Excel report, and PDF report.
- Do not generate additional language variants unless the user explicitly requests them.

### Initial operating model

- The first version runs locally.
- The user creates and configures dashboard projects through prompts to the agent.
- Provide a simple browser-based graphical setup experience for that conversation and workflow.
- Serve the interface locally from the user's computer as a browser application rather than a native desktop UI.
- Bind the local web application to the loopback interface only.
- Do not expose the application to other devices on the local network.
- A public or multi-user project-creation service is not part of the initial version.
- Support Windows and Linux in the first version.
- macOS support is out of scope initially.
- Provide a guided installer for Windows.
- Provide an installation script for Linux.
- Do not require Docker for initial installation.

### Hermes runtime and learning

- The project installs and manages its own Hermes Agent runtime.
- Do not depend on a separately installed global Hermes instance.
- Hermes should learn each user's dashboard expectations over time.
- Persist only non-confidential user preferences, approved terminology, visual choices, and feedback.
- Never store source records, report values, or confidential content in Hermes memory.
- Do not retain complete agent conversation transcripts.
- After each conversation, save only a compact non-confidential context needed for future conversations.
- During setup, ask the user to authenticate with the AI agent/provider account or accounts they use.
- Do not assume one predetermined AI provider for every user.
- Initial provider/account support: Claude, Codex, Gemini, and DeepSeek.
- When multiple providers are connected, let Hermes select the provider for each task.
- Prefer the provider expected to complete the task with the fewest tokens.
- If the user explicitly requests a specific agent/provider, honor that selection instead of automatic routing.
- If the selected provider fails or is unavailable, ask the user before retrying with another provider.
- Do not perform automatic cross-provider fallback.
- Save provider login credentials in the operating system's secure credential store for future sessions.
- Never store provider credentials in dashboard project files.

### Reference sample formats

- Accept Excel workbooks (`.xlsx`).
- Accept PDF reports (`.pdf`).
- Accept dashboard screenshots and image files.
- CSV and JSON are not reference-sample formats in the first version.

### API data format and onboarding

- API onboarding accepts an endpoint URL plus optional OpenAPI/Swagger input or representative JSON.
- API responses are JSON only; XML, CSV, and other API response formats are out of scope.
- Support API key, Bearer token, and OAuth authentication without storing secrets in project files.
- Support bounded retries, rate limits, timeouts, and cursor-, page-, or link-based pagination.
- Use incremental refresh only after the user confirms a cursor or updated-time field; otherwise use a full snapshot.
- Explain inferred fields and mappings in business language and require confirmation before use.

### Initial preview data sources

- The agent may create synthetic data for dashboard previews.
- If the user uploads a reference sample containing usable data, the preview may instead use data extracted from that sample.
- Always generate and present a synthetic preview before using extracted sample data.
- Use extracted sample data only after the user approves the synthetic preview and explicitly authorizes extracted-data use.

### Agent-assisted dashboard population

- Allow the user to ask the agent to populate an existing dashboard with newly supplied data.
- Accept data through a user-uploaded file or a user-specified extraction location.
- Supported population file formats are CSV and Excel.
- Clearly display the supported formats to the user before file selection or upload.
- A user-specified extraction location may be a local file or local folder path only.
- URLs and cloud-storage locations are out of scope for initial dashboard population.
- When a selected folder contains multiple supported files, analyze all supported files.
- Ask the user to confirm how those files relate before combining their data.
- Before populating the dashboard, show detected columns, proposed field mappings, row counts, validation problems, and confidential-field classifications.
- Require user approval of that import summary before applying any data.
- Ask the user to choose an import mode: replace current data, append records, or update matching records.
- For update mode, propose the identifier used to match records and require user confirmation before applying updates.
- Allow imported data to be saved in the project folder only after the user confirms it is non-confidential.
- Never persist imported data classified as confidential.
- Pasted conversation data and manual data-entry forms are not required for this workflow.
- Use the project's previously approved schema, field mappings, terminology, and compact non-confidential context to place that data correctly.
- Do not require the user to redefine an already approved dashboard structure.
- Validate supplied values against the approved schema before using them.
- Apply all confidential-data permission, memory, storage, display, report, and deletion rules to agent-assisted population.

### Confidential data handling

- Detect fields that are likely to contain personal, sensitive, or confidential data and ask the user to confirm the classification.
- Allow the user to manually add or remove confidential classifications.
- Do not treat an unrecognized field as safe solely because automatic detection did not flag it.
- Before using any data extracted from an uploaded sample, ask the user for explicit permission.
- Analyze confidential uploads from temporary storage only.
- Delete the temporary confidential source immediately after analysis finishes.
- Do not retain confidential data in application storage, databases, logs, caches, prompts, or intermediate artifacts.
- Confidential data may be persisted only inside the final report explicitly requested and approved by the user.
- Prefer synthetic preview data whenever permission to use extracted data has not been granted.
- Reports containing confidential data must be offered as an immediate download only.
- Delete the application's temporary copy of a confidential report immediately after download.
- Save reports locally only when they contain no confidential data.
- Clearly explain the storage and deletion behavior to the user before report generation and download.
- A local web dashboard may display authorized confidential data temporarily in memory.
- Do not persist that in-memory confidential dashboard data.
- In a future nonlocal deployment, never display confidential data in the web dashboard.
- In a nonlocal deployment, restrict authorized confidential data to immediate-download Excel or PDF reports under the same temporary-file deletion rules.

### Output selection

- Let the user choose which outputs to generate for each project.
- Available outputs are a local web dashboard, an Excel report, and a PDF report.
- Do not generate an unselected output.

### Execution model and scheduling

- Generate dashboards and reports on demand unless the user explicitly enables a schedule.
- Scheduling is permitted only after the project and its source data are confirmed non-confidential.
- Offer daily, weekly, and monthly presets plus an advanced cron expression with a timezone preview.
- Scheduled jobs run locally and deliver only to a selected local folder; email and cloud delivery are out of scope.
- Keep the latest 10 successful report sets by default, with a user-configurable retention limit.
- A failed or partial run must never replace the last successful report.
- Never activate scheduling without explicit user approval.

### Project persistence

- Save non-confidential project settings locally so a project can be reopened and reused.
- Store project settings as readable files inside a local project folder.
- Let the user choose the local save location for each dashboard project.
- Copy non-confidential uploaded reference samples into the selected project folder.
- Do not require a database for initial project configuration storage.
- Support YAML and JSON project configuration files.
- Use YAML for smaller configurations intended to be easy for a person to read or edit.
- Use JSON for larger configurations generated by the agent.
- Persist approved schemas, colors, layouts, terminology, output preferences, and approval metadata.
- Do not include confidential source values in the saved project configuration.
- Keep version history for approved non-confidential schemas and layouts.
- Allow the user to roll back to an earlier approved version.

### Preview approval

- Approval is organized by report section, not separately by output format.
- Sections may include the summary, KPI groups, charts, detailed tables, and agent insights.
- An approved section applies consistently to every selected output format.
- Always use synthetic data during the structure and design approval stage.
- Track dependencies between report sections.
- A rejected section blocks only the sections that depend on it.
- Independent approved sections may proceed while the rejected section is revised.
- Allow the user to define section dependencies manually.
- When the user does not define them, the agent may infer dependencies from the sample and proposed schema.
- If the agent is uncertain about a dependency, ask the user to confirm it instead of assuming.

### Metrics and calculations

- Detect formulas and implied KPIs in the reference sample.
- Explain every proposed calculation in plain business language.
- Require explicit user approval for each proposed calculation before using it in a preview.
- Execute approved calculations with deterministic code rather than model-generated arithmetic.

### Visual design

- When a reference sample is provided, make the first preview closely reproduce its visual design.
- Do not redesign or modernize the sample by default.
- The agent may propose and generate a cleaner design when the user explicitly asks for one.
- When no reference sample is supplied, ask the user about preferred colors and visual style.
- Use those confirmed preferences to create an original design.
- Allow the user to upload PNG, JPEG, or SVG branding images for the dashboard and reports.
- Allow natural-language preview revisions through the agent.
- Also provide direct local-interface controls for colors, chart types, and section order.

## Deferred requirements

- Nonlocal and multi-user deployment.
- macOS packaging and support.

These deferred requirements require a new user discovery and approval cycle before implementation. Do not infer them from the initial local version.
