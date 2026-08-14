# Final Implementation v2 — Release Hardening and Upgrade Plan

## Purpose

Define the follow-up work after the Windows v0.1.0 release workflow is stable.
The v2 milestone improves maintainability, release diagnostics, runtime currency,
and end-user recovery without enabling external scheduling or delivery.

The application remains local-first, Windows x64 first, privacy-preserving, and
based only on synthetic public examples in tests and documentation.

## 1. Runtime and dependency modernization

- [x] Select Node.js 24.18.0 LTS for v0.2.1.
- [x] Update `.nvmrc`, frontend `engines`, lockfile metadata, CI, and bundled runtime checks together.
- [ ] Build and test with the selected Node.js version on Windows and Linux (Linux passed; Windows runner pending).
- [x] Confirm Next.js, React, Playwright, and native dependencies remain compatible on Linux.
- [x] Keep the minimum-version error clear for users running the development installer.
- [x] Record the selected Node.js, Python, Hermes, Playwright, Chromium, and installer versions in release manifest schema v2.
- [x] Keep runtime versions aligned across workflow, diagnostics, and installers.

## 2. Release workflow reliability

- [x] Upload the generated `Setup.exe`, checksum, manifest, and install logs as workflow artifacts before release creation.
- [x] Preserve sanitized diagnostic artifacts when a later release step fails.
- [x] Print the exact failing file for every secret-scan match without printing the matched secret.
- [x] Keep binary files out of text-based secret scanning while retaining checks for credentials in source/config files.
- [x] Add a workflow dispatch option for maintainers to rebuild a release candidate without moving a production tag.
- [x] Validate that a release commit is contained in `main` before building.
- [x] Reject duplicate or already-published tags with an actionable message.
- [x] Add a dry-run packaging mode that does not create or modify a GitHub Release.
- [x] Keep public release publication as a separate, manual approval step.

## 3. Installer and upgrade behavior

- [ ] Test upgrades from v0.1.0/v0.2.0 to v0.2.1 on a clean Windows VM without deleting project folders, reports, provider configuration, or Hermes authentication state.
- [x] Preserve user-owned data while replacing only application-managed files.
- [x] Make failed upgrades transactional and recoverable, with a synthetic failure check in release CI.
- [x] Add an installer version marker and a readable migration summary.
- [ ] Validate silent installation and uninstallation on a clean Windows x64 VM.
- [x] Keep the installer per-user and unsigned until code signing is approved and available.
- [x] Document SmartScreen and checksum verification for every unsigned build.

## 4. Diagnostics and supportability

- [x] Add a redacted support bundle containing versions, health checks, and sanitized operational events.
- [x] Exclude OAuth tokens, API keys, bearer tokens, raw subprocess output, project paths, and project values from diagnostics.
- [x] Add a UI view for API, web, Hermes, browser, storage, provider, and Codex-model status.
- [x] Show actionable remediation when a local process, port, or dependency is unavailable.
- [x] Add a copyable diagnostic identifier without exposing sensitive content.
- [x] Document how to collect diagnostics from Windows and Linux installations.

## 4.1 Contextual guidance and tab content

- [x] Display “O agente faz uma pergunta por vez e não presume requisitos ausentes.” only at the start of guided intake.
- [x] Do not repeat this guidance text in every tab or persistent application header.
- [x] Keep each tab focused on its own task and show help text only where it is actionable.
- [x] In “Este entendimento está correto?”, show the agent's deterministic understanding summary before confirmation.

## 4.2 Synthetic dashboard review follow-ups

- [x] Diagnose and add one bounded structured retry for invalid Hermes draft responses.
- [x] Show a user-facing remediation message while preserving the active specification.
- [x] Validate the project directory as an absolute local path before activation.
- [x] Show accepted path examples and return field-level validation errors without echoing rejected values.
- [x] Cover Hermes rejection/retry with API tests and project activation with English/Portuguese browser E2E.

## 4.3 Visual theme follow-up

- [x] Replace the current green visual palette with a professional navy/blue primary palette.
- [x] Define blue light/dark tokens with accessible text and focus-state contrast.
- [x] Preserve semantic colors for success, warning, error, pending, and blocked states.
- [ ] Update screenshots, visual tests, and user documentation after the palette change.

## 5. Provider and OAuth resilience

- [x] Test OAuth expiry, cancellation, duplicate login, process termination, and existing-login recovery after application restart.
- [x] Show a recoverable state when browser login is interrupted, cancelled, expired, or fails.
- [x] Continue to persist only secret-free provider references in project metadata.
- [x] Add explicit Codex/gpt-5.5 compatibility checks before an authenticated revision task.
- [x] Keep API-key providers in the operating-system credential store.
- [ ] Add a manual acceptance test for Codex OAuth with `gpt-5.5` using synthetic prompts only.

## 6. Test matrix

- [x] Run the complete local Python, frontend, browser, privacy, parity, and packaging suites.
- [ ] Test Windows 10 and Windows 11 x64 clean machines.
- [ ] Test development installation with current and minimum supported Python/Node versions.
- [ ] Test offline installation with network access disabled after the installer is downloaded.
- [ ] Test restart, upgrade, rollback/failure cleanup, and uninstall preservation.
- [ ] Test English and Portuguese provider onboarding.
- [x] Test web, XLSX, and PDF output parity from the same approved `DashboardSpec`.
- [ ] Record every clean-machine result in this file before release approval.

## 7. Documentation and release policy

- [x] Update README installation instructions for the selected v0.2.1 runtimes.
- [x] Add a maintainer runbook for candidate builds, tag creation, artifact inspection, and draft releases.
- [x] Document the difference between workflow artifacts, draft releases, and published releases.
- [x] Document the safe procedure for replacing a failed release tag.
- [x] Keep external scheduling and delivery disabled unless the user explicitly approves activation.
- [x] Never publish a GitHub Release automatically.
- [x] Use synthetic public examples in all new fixtures and support instructions.

## Completion criteria

The v2 milestone is complete only when:

1. The selected Node.js LTS version passes the full compatibility matrix.
2. A clean Windows x64 machine installs and upgrades offline successfully.
3. Release failures retain enough redacted artifacts to diagnose them.
4. OAuth, dashboard generation, report parity, restart, and uninstall checks pass.
5. Documentation and manifests accurately identify every bundled runtime.
6. A maintainer has explicitly approved any public release or external activation.

## Current known follow-ups

- Node.js 24.18.0 LTS is now pinned for v0.2.1; Linux build and browser tests
  pass, while the Windows release runner remains an acceptance gate.
- The release workflow now avoids binary false positives in the secret scanner;
  future changes should retain the file-level diagnostics.
- The v0.1.0 clean-machine acceptance record remains a prerequisite for public
  publication and is not replaced by automated CI results.

## v0.2.1 automated validation record

- 115 Python tests passed after installed-launcher, provider-setup, and project-home remediation.
- Frontend typecheck and production build passed with verified Node.js 24.18.0.
- English and Portuguese browser journeys passed across API restarts, including
  the project home, new-project action, and reopening an active project.
- Version coherence, workflow YAML, shell syntax, privacy-oriented support bundle,
  structured Hermes retry, and renderer/parity tests passed locally.
- No GitHub Release was created or published and no scheduling/delivery was activated.

## Remaining manual gates

- [ ] Run the v0.2.1 release workflow on the Windows runner and inspect retained artifacts.
- [ ] Complete clean Windows 10 and Windows 11 x64 install, OAuth, report, restart, upgrade, rollback, and uninstall acceptance.
- [ ] Record the installer checksum and VM results here.
- [ ] Obtain explicit user approval before publishing any draft release.

## Post-draft application remediation

- [x] Recover automatically when a stale managed frontend is left without its API.
- [x] Capture local API and web startup logs and report actionable port conflicts.
- [x] Offer API-key provider setup in the review before a project exists.
- [x] Distinguish provider/runtime failures from invalid structured Hermes drafts.
- [x] Add a project home with create, list, open, and return navigation.
- [x] Reopen only checksum-verified active project specifications.
- [x] Cover the home/reopen flow in English and Portuguese browser tests.
- [ ] Rebuild the Windows draft candidate and run stale-launch recovery on the Windows runner.
