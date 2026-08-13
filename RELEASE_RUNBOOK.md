# Universal Dashboard Agent v0.2.0 Release Runbook

## Candidate build

1. Confirm `main` is clean, reviewed, and contains version `0.2.0` everywhere:

   ```bash
   python scripts/check-version.py --tag v0.2.0
   ```

2. In GitHub Actions, run **draft-release** with `mode=dry-run` and
   `version=0.2.0`. This builds and tests the installer without creating or
   modifying a GitHub Release.
3. Download the workflow artifact and inspect the Setup.exe,
   `SHA256SUMS.txt`, release manifest, install/upgrade logs, and sanitized
   workflow diagnostics.

## Draft release

After the dry run passes, create the release tag from the reviewed `main`
commit:

```bash
git checkout main
git pull --ff-only
git tag v0.2.0
git push origin v0.2.0
```

The tag workflow creates a **draft** release. It never publishes it.

If a build fails before a release exists, fix and merge the problem first. Only
then replace the failed tag after confirming `gh release view v0.2.0` reports
that no draft or published release exists:

```bash
git tag -f v0.2.0
git push origin :refs/tags/v0.2.0
git push origin v0.2.0
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
