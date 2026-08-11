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
