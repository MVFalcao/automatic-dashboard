# Final Implementation and v0.1.0 Release Plan

## Summary

Convert the completed MVP into a Windows-first public release. The target is an unsigned, offline, per-user Windows x64 `Setup.exe`, initially created as a draft GitHub Release. Public publication remains manual and requires an authenticated clean-machine acceptance test.

## Implementation Changes

### 1. Finalize the nontechnical user experience

- Add visual Codex OAuth onboarding to the existing provider section.
- Add authenticated local API operations to start, poll, and cancel a Codex OAuth session.
- Return only a temporary verification URL, user code, expiry and sanitized status. Never expose or persist OAuth tokens in the application.
- Run the managed Hermes login with `--no-browser`, maintain one bounded login process per session and terminate it on cancellation, expiry or shutdown.
- Reuse an existing authenticated Codex session when available.
- After login, select `openai-codex` and `gpt-5.5`, persisting only a secret-free `ProviderConnection`.
- Show pending, connected, expired, cancelled and failed states in English and Portuguese.
- Add a visual “Connect Codex” flow; retain API-key onboarding for Claude, Gemini and DeepSeek.
- Make the Windows launcher wait for readiness, open `http://127.0.0.1:3000`, prevent duplicate starts and stop owned processes on shutdown.

### 2. Build the Windows Setup.exe

- Add a pinned Inno Setup definition for Universal Dashboard Agent 0.1.0.
- Use per-user installation with no administrator requirement at `%LOCALAPPDATA%\\UniversalDashboardAgent`.
- Package an offline Windows x64 bundle containing Python 3.12, Node 20.9, Hermes 0.13.0 plus `aiohttp==3.13.3`, Chromium, the application wheel and the Next.js standalone build.
- Exclude tests, caches, development dependencies, intermediate build output, reports, data and private/ignored samples.
- Validate `manifest.sha256`; add Start Menu shortcuts; preserve user configuration and Hermes auth state on reinstall.
- Stop owned processes before uninstalling and document that the v0.1.0 executable is unsigned.
- Produce `UniversalDashboardAgent-0.1.0-windows-x64-setup.exe`, recording compressed/installed sizes and failing if the asset exceeds 2 GiB.

### 3. Automate versioning and draft releases

- Keep 0.1.0 consistent across Python, frontend and API metadata.
- Add version/tag coherence checks.
- Add a tag-triggered `release.yml` workflow for `v*` tags from `main`.
- Build, checksum, scan, install, smoke-test and uninstall the offline Setup.exe on a Windows runner with package indexes disabled.
- Generate `SHA256SUMS.txt` and a machine-readable release manifest.
- Create a draft GitHub Release with only the Setup.exe, checksums and manifest. Never publish automatically.

### 4. Documentation and release handoff

- Replace the obsolete README next-step text with end-user installation, first-run, OAuth, startup, shutdown and uninstall instructions.
- Document SmartScreen warnings, checksum verification and the maintainer release sequence.
- Update implementation/remediation documentation only as acceptance items complete.
- Retain Linux as a tested technical bundle, but do not publish it as a supported v0.1.0 end-user artifact.

## Test and Acceptance Plan

- Unit-test OAuth lifecycle, sanitization, duplicate prevention, cancellation, expiry, existing-login detection and secret-free persistence.
- Browser-test English and Portuguese Codex onboarding with a fake Hermes process; verify tokens and raw subprocess output never reach the DOM, logs or project files.
- Test launcher readiness, duplicate launch, browser opening and owned-process shutdown.
- Test checksum rejection, private-file exclusion, silent install, reinstall preservation, failed-install cleanup and safe uninstall.
- Run Python, frontend, parity, privacy, E2E and clean-install suites.
- On a clean Windows x64 VM without Python or Node: verify the checksum, install offline, launch from Start Menu, complete visual Codex OAuth, verify unauthenticated rejection, complete a structured `gpt-5.5` task, run synthetic intake/approval, generate web/XLSX/PDF outputs, restart, then uninstall without touching external project/report folders.
- Record the VM result here. Publish the draft release only after explicit user approval.

## Assumptions and Completion Criteria

- Initial public platform: Windows x64.
- Version/tag: 0.1.0 / v0.1.0.
- Distribution: full offline Setup.exe.
- Installer: pinned Inno Setup, per-user.
- Signing unavailable for v0.1.0; checksums and an unsigned-publisher warning are mandatory.
- Final acceptance provider: OpenAI Codex OAuth with gpt-5.5.
- External delivery and scheduling remain disabled unless separately approved.
- Final delivery requires a passing clean-machine acceptance record and explicit promotion of the draft GitHub Release.

## Execution status

- [x] Repository instructions read and plan recorded.
- [x] Visual Codex OAuth API/UI lifecycle implemented with secret-free status and persistence.
- [x] Offline bundle, Inno Setup definition, checksums, release manifest and draft-release workflow implemented.
- [x] Version coherence, installer safety, OAuth unit tests and existing test suites validated locally (100 Python tests plus frontend typecheck).
- [ ] Clean Windows x64 VM acceptance with visual OAuth and offline Setup.exe.
- [ ] User approval to publish the draft GitHub Release.
