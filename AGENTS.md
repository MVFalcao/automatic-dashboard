# Repository guidance

## Purpose

Build the generic, Hermes-powered dashboard platform described in
`IMPLEMENTATION_PLAN.md`.

## Working rules

- Read `.hermes.md`, `context.md`, and `IMPLEMENTATION_PLAN.md` first.
- Keep the core platform independent of any business domain.
- Treat files ignored as private source samples as read-only.
- Use synthetic data in fixtures and public examples.
- Keep authoritative calculations deterministic and tested.
- Validate model-produced schemas and insights before using them.
- Keep API credentials in environment variables or a secret manager.
- Never activate external delivery or scheduling without user approval.
- Update tests and documentation with behavior changes.

## Directory boundaries

- `automation/adapters/`: external API integrations.
- `automation/discovery/`: sample and API analysis.
- `automation/normalization/`: canonical data mapping.
- `automation/metrics/`: deterministic calculations.
- `automation/agent/`: Hermes orchestration and structured prompts.
- `automation/reports/`: report coordination.
- `automation/privacy/`: redaction and publication checks.
- `automation/pipeline/`: end-to-end execution.
- `dashboard/api/`: application API.
- `dashboard/web/`: web interface.
- `config/schemas/`: versioned machine-readable contracts.
- `examples/`: synthetic, publishable examples only.
- `templates/`: Excel and PDF rendering templates.
- `reports/` and `data/`: generated local artifacts, ignored by default.
