# Review Remediation Plan

## Goal

Make the tested dashboard foundation a fully connected, release-ready local
Windows/Linux product. Keep loopback-only operation, synthetic previews before
real data, explicit approvals, deterministic metrics, no automatic provider
fallback, and no confidential persistence.

## Milestones

1. **R1 Security/privacy boundaries** — mandatory source/import approvals and
   reviewed classifications; SSRF and cross-origin pagination protection; XLSX
   formula escaping; confidential-artifact TTL/cleanup; Windows auth parity.
2. **R2 Persistence** — restart-safe project aggregate linking sources,
   inspections, approvals, specs, checkpoints, providers, drift drafts, and
   schedules while keeping secrets/source values out of files and SQLite.
3. **R3 Real UI workflow** — connect intake, inspection, approvals, previews,
   imports, reports, providers, sources, and schedules; remove hardcoded review
   state; support English and Portuguese restart-safe browser E2E flows.
4. **R4 Hermes operation** — start/health-check authenticated loopback gateway,
   real `/v1` transport, OS keyring, provider login/status, routing/fallback,
   structured validation, and filtered memory.
5. **R5 Scheduling execution** — reconcile Hermes cron jobs, run the real
   deterministic pipeline, persist bindings, retain independent artifact sets,
   and preserve the last success across failures/restarts.
6. **R6 Renderer parity** — one filtered report document for web/XLSX/PDF with
   approved sections, filters, layout, terminology, localization, outputs, and
   selected-folder persistence.
7. **R7 Localization/design** — apply locale formatting and reproduce approved
   reference styles with confidence and synthetic-data privacy guarantees.
8. **R8 Release/CI** — self-contained user-scoped installers, clean-machine
   Windows/Linux smoke tests, loopback/auth checks, privacy scans, and mandatory
   GitHub Actions.

## Release gates

- Zero unresolved P0/P1 findings.
- Full Python, TypeScript, build, privacy, security, parity, E2E, and installer
  suites pass on clean Windows and Linux environments.
- Complete English and Portuguese flows pass from intake through approved spec,
  real source data, deterministic metrics, reports, restart, and scheduling.
- No credentials, confidential values, or source records appear in prompts,
  logs, SQLite, caches, project files, or public examples.

## Execution rules

- Keep each milestone as a separate logical commit in the review PR when the
  user requests a single-PR remediation pass.
- Run the full relevant suite before publishing each commit group.
- Do not activate external delivery or scheduling without explicit approval.
- Re-run an independent security/release review after R8.

## Current execution

PR #19 was merged, and the post-review R1–R8 completion pass is implemented on
the `agent/remediation-r1` branch. On 2026-08-12 the local Linux release gates
passed: the full Python suite, TypeScript check, production web build, npm
audit, privacy scan, English/Portuguese browser journeys across two API
restarts, and a checksum-verified offline install containing pinned Python,
Node, Chromium, application, and Hermes runtimes. CI now repeats the offline
Linux proof with package indexes disabled and retains a clean Windows install
job.

The published release-candidate commits passed all GitHub Actions, including
the real Windows runner. On 2026-08-12 an explicitly approved acceptance run
also used the public GitHub issues API as a real source: 20 records were
processed in memory, three sections were approved, web/XLSX/PDF artifacts were
generated, restart persistence passed, the temporary local schedule was
disabled afterward, and a sampled source value did not appear in project or
SQLite metadata. That run exposed and fixed configured API query loss and a
first-run diagnostic that selected system Node instead of the bundled runtime.

On 2026-08-13 the remaining provider acceptance gate passed on Windows using
the native credential manager and an explicitly connected OpenAI Codex OAuth
account. The managed Hermes gateway bound to loopback, rejected an
unauthenticated `/v1/chat/completions` request, completed an authenticated
synthetic structured task with `gpt-5.5`, returned validated JSON, and reported
usage. Temporary gateway credentials were removed after each attempt and no
provider token was printed or copied into the project.

The authenticated run exposed and fixed Hermes 0.13 runtime-contract gaps: the
gateway now starts with `hermes gateway run`, the required API-server
`aiohttp==3.13.3` adapter is pinned in online and offline installations, and
first-run guidance includes provider/model selection after authentication. It
also exposed an oversized WSL-to-Windows source copy; Windows installation now
excludes generated `node_modules` and `.next` trees. The final provider
acceptance requirement is satisfied. The independent review found and fixed
the Hermes subprocess-output risk, with no other open P0/P1 finding in the
reviewed diff.
