# Universal Dashboard Agent v0.2.1 Release Runbook

## Candidate build

1. Before pushing, load the pinned Node runtime and run the local release
   preflight from WSL:

   ```bash
   source ~/.nvm/nvm.sh
   nvm use
   bash scripts/test-release-local.sh
   ```

   This checks coherent versions, release packaging tests, the clean frontend
   install/typecheck/build, the Git diff, and Windows PowerShell syntax. It does
   not build or install the Windows `.exe` from Linux.

2. Confirm `main` contains version `0.2.1` everywhere:

   ```bash
   python scripts/check-version.py --tag v0.2.1
   ```

3. In GitHub Actions, run **draft-release** with `mode=dry-run` and
   `version=0.2.1`. This builds and tests the installer without creating or
   modifying a GitHub Release.
4. Download the workflow artifact and inspect the Setup.exe,
   `SHA256SUMS.txt`, release manifest, install/upgrade logs, and sanitized
   workflow diagnostics.

The Windows install/upgrade/rollback/uninstall acceptance logic lives in
`scripts/test-windows-release.ps1`. GitHub Actions calls that file directly.
When a local Windows bundle and Setup.exe are available, run the exact same test
from Windows PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-windows-release.ps1 `
  -SetupPath C:\path\to\UniversalDashboardAgent-0.2.1-windows-x64-setup.exe `
  -BundleDir C:\path\to\dashboard-bundle
```

The test uses a temporary application directory and removes it after checking
installation, upgrade persistence, loopback health, failed-upgrade rollback,
and uninstall behavior. It does not remove external project folders.

## Draft release

After the dry run passes, create the release tag from the reviewed `main`
commit:

```bash
git checkout main
git pull --ff-only
git tag v0.2.1
git push origin v0.2.1
```

The tag workflow creates a **draft** release. It never publishes it.

If a build fails before a release exists, fix and merge the problem first. Only
then replace the failed tag after confirming `gh release view v0.2.1` reports
that no draft or published release exists:

```bash
git tag -f v0.2.1
git push origin :refs/tags/v0.2.1
git push origin v0.2.1
```

Never replace a tag that already has a draft or published release. Use a new
patch version instead.

## Artifact meanings

- A **workflow artifact** is a temporary, authenticated build result retained
  for 14 days. Dry runs produce these and do not create a release.
- A **draft release** is visible to repository maintainers and contains only the
  tested Setup.exe, checksum file, and release manifest.
- A **published release** is public distribution and requires explicit user
  approval after clean-machine acceptance.

## Clean-machine acceptance

On clean Windows 10 and Windows 11 x64 virtual machines without Python or Node:

1. Verify the Setup.exe SHA-256 against `SHA256SUMS.txt`.
2. Install offline and confirm the browser opens only on `127.0.0.1`.
3. Complete Codex OAuth with `openai-codex` and `gpt-5.5` using a synthetic
   prompt.
4. Complete English and Portuguese intake/review flows with synthetic data.
5. Generate matching web, XLSX, and PDF outputs.
6. Restart the application and verify project/provider persistence.
7. Upgrade a v0.1.0 installation and verify configuration, authentication, and
   external project/report folders are preserved.
8. Uninstall and verify only application-managed files are removed.
9. Record the OS versions, checksum, results, and failures in
   `final_implementation_v2.md`.

Do not publish the draft, enable external delivery, or activate scheduling as
part of this runbook without explicit user approval.
