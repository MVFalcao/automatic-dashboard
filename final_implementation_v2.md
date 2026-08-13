# Final Implementation v2 — Release Hardening and Upgrade Plan

## Purpose

Define the follow-up work after the Windows v0.1.0 release workflow is stable.
The v2 milestone improves maintainability, release diagnostics, runtime currency,
and end-user recovery without enabling external scheduling or delivery.

The application remains local-first, Windows x64 first, privacy-preserving, and
based only on synthetic public examples in tests and documentation.

## 1. Runtime and dependency modernization

- [ ] Select a currently supported Node.js LTS line for v2.
- [ ] Update `.nvmrc`, frontend `engines`, lockfile metadata, CI, and bundled runtime checks together.
- [ ] Build and test with the selected Node.js version on Windows and Linux.
- [ ] Confirm Next.js, React, Playwright, and native dependencies remain compatible.
- [ ] Keep the minimum-version error clear for users running the development installer.
- [ ] Record the selected Node.js, Python, Hermes, and Playwright versions in the release manifest.
- [ ] Do not change runtime versions independently in the workflow and installer.

## 2. Release workflow reliability

- [ ] Upload the generated `Setup.exe`, checksum, and manifest as workflow artifacts before release creation.
- [ ] Preserve diagnostic artifacts when a later release step fails.
- [ ] Print the exact failing file for every secret-scan match.
- [ ] Keep binary files out of text-based secret scanning while retaining checks for credentials in source/config files.
- [ ] Add a workflow dispatch option for maintainers to rebuild a release candidate without moving a production tag.
- [ ] Validate that a tag points to `main` before building.
- [ ] Reject duplicate or already-published tags with an actionable message.
- [ ] Add a dry-run packaging job that does not create or modify a GitHub Release.
- [ ] Keep public release publication as a separate, manual approval step.

## 3. Installer and upgrade behavior

- [ ] Test upgrades from v0.1.0 to v2 without deleting project folders, reports, provider configuration, or Hermes authentication state.
- [ ] Preserve user-owned data while replacing only application-managed files.
- [ ] Make failed upgrades transactional and recoverable.
- [ ] Add an installer version check and a readable migration summary.
- [ ] Validate silent installation and uninstallation on a clean Windows x64 VM.
- [ ] Keep the installer per-user and unsigned until code signing is approved and available.
- [ ] Document SmartScreen and checksum verification for every unsigned build.

## 4. Diagnostics and supportability

- [ ] Add a redacted support bundle containing versions, health checks, and sanitized logs.
- [ ] Never include OAuth tokens, API keys, bearer tokens, raw subprocess output, or project values in diagnostics.
- [ ] Add a UI view for API, web, Hermes, browser, storage, and provider status.
- [ ] Show actionable remediation when a local process, port, or dependency is unavailable.
- [ ] Add a copyable diagnostic identifier without exposing sensitive content.
- [ ] Document how to collect diagnostics from Windows and Linux installations.

## 4.1 Contextual guidance and tab content

- [ ] Display “O agente faz uma pergunta por vez e não presume requisitos ausentes.” only in the guided intake/onboarding context.
- [ ] Do not repeat this guidance text in every tab or persistent application header.
- [ ] Keep each tab focused on its own task and show help text only where it is actionable.
- [ ] In the “Este entendimento está correto?” tab, show the agent's understanding/note before the user confirms; this is recorded as a future modification and is intentionally not implemented in the current release.

## 5. Provider and OAuth resilience

- [ ] Test OAuth expiry, cancellation, duplicate login, process termination, and application restart.
- [ ] Show a recoverable state when the browser login is interrupted.
- [ ] Continue to persist only secret-free provider references in project metadata.
- [ ] Add explicit model/provider compatibility checks before an authenticated task.
- [ ] Keep API-key providers in the operating-system credential store.
- [ ] Add a manual acceptance test for Codex OAuth with `gpt-5.5` using synthetic prompts only.

## 6. Test matrix

- [ ] Run the complete Python, frontend, browser, privacy, parity, and packaging suites.
- [ ] Test Windows 10 and Windows 11 x64 clean machines.
- [ ] Test development installation with current and minimum supported Python/Node versions.
- [ ] Test offline installation with network access disabled after the installer is downloaded.
- [ ] Test restart, upgrade, rollback/failure cleanup, and uninstall preservation.
- [ ] Test English and Portuguese provider onboarding.
- [ ] Test web, XLSX, and PDF output parity from the same approved `DashboardSpec`.
- [ ] Record every clean-machine result in this file before release approval.

## 7. Documentation and release policy

- [ ] Update README installation instructions for the selected v2 runtimes.
- [ ] Add a maintainer runbook for candidate builds, tag creation, artifact inspection, and draft releases.
- [ ] Document the difference between workflow artifacts, draft releases, and published releases.
- [ ] Document the safe procedure for replacing a failed release tag.
- [ ] Keep external scheduling and delivery disabled unless the user explicitly approves activation.
- [ ] Never publish a GitHub Release automatically.
- [ ] Use synthetic public examples in all new fixtures, screenshots, and support instructions.

## Completion criteria

The v2 milestone is complete only when:

1. The selected Node.js LTS version passes the full compatibility matrix.
2. A clean Windows x64 machine installs and upgrades offline successfully.
3. Release failures retain enough redacted artifacts to diagnose them.
4. OAuth, dashboard generation, report parity, restart, and uninstall checks pass.
5. Documentation and manifests accurately identify every bundled runtime.
6. A maintainer has explicitly approved any public release or external activation.

## Current known follow-ups

- The v0.1.0 workflow currently pins Node.js 20.9.0 for reproducibility; v2 should
  evaluate and test a newer supported LTS before changing the pin.
- The release workflow now avoids binary false positives in the secret scanner;
  future changes should retain the file-level diagnostics.
- The v0.1.0 clean-machine acceptance record remains a prerequisite for public
  publication and is not replaced by automated CI results.
