"""Guided intake: Q&A state, template selection, and the draft/feedback loop."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from automation.agent.client import call_hermes_json
from automation.agent.managed import managed_hermes
from automation.agent.memory import MemoryKind, safe_memory_store
from automation.approval.models import ApprovalPackage, CreateApprovalRequest
from automation.approval.service import approval_store
from automation.discovery.models import Confidence, DraftDashboardSchema, FieldType, ProposedField, ProposedSection
from automation.reports import ReportDocument, build_report_document
from automation.release.support import support_events
from automation.specification.models import (
    DashboardSpec, FieldKind, FieldMapping, LayoutSpec,
    LocalizationSpec, OutputKind, OutputSpec, PrivacyPolicy,
    StyleSpec, VisualizationKind,
)
from automation.specification.templates import (
    DOMAIN_TEMPLATES,
    DomainTemplate,
    apply_template_overrides,
    build_generic_template,
    find_sensitive_labels,
)
from dashboard.api.intake import (
    IntakeAnswerRequest,
    IntakeResponse,
    StartIntakeRequest,
    intake_store,
)
from dashboard.api.projects import project_repository


class IntakeWorkspacePreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document: ReportDocument
    approval: ApprovalPackage
    project_id: UUID | None = None
    template_id: str | None = None
    template_reasoning: str | None = None


class HermesTemplateSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_id: str
    reasoning: str = Field(min_length=1, max_length=500)
    field_label_overrides: dict[str, str] = Field(default_factory=dict)
    section_title_overrides: dict[str, str] = Field(default_factory=dict)
    metric_label_overrides: dict[str, str] = Field(default_factory=dict)


class IntakeProjectLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: UUID


class PreviewDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accent_color: str = Field(default="#1D4ED8", pattern=r"^#[0-9a-fA-F]{6}$")
    chart_type: str = Field(default="bar", pattern=r"^(bar|line|pie)$")
    section_order: list[str] = Field(min_length=1)
    terminology: dict[str, str] = Field(default_factory=dict)
    feedback: str | None = None
    feedback_non_confidential: bool = False


class FeedbackTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feedback: str
    reasoning: str
    version: int


class PreviewDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int
    status: str = "draft"
    accent_color: str
    chart_type: str
    section_order: list[str]
    terminology: dict[str, str]
    feedback_applied_by_hermes: bool = False
    feedback_reasoning: str | None = None
    feedback_history: list[FeedbackTurn] = Field(default_factory=list)


class HermesDraftProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accent_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    chart_type: str = Field(pattern=r"^(bar|line|pie)$")
    section_order: list[str] = Field(min_length=1)
    terminology: dict[str, str] = Field(default_factory=dict)
    reasoning: str = Field(min_length=1, max_length=400)


router = APIRouter(prefix="/api/intake", tags=["intake"])


def _template_selection_prompt(
    session: object,
    exclude_template_ids: Sequence[str],
    *,
    repair_attempt: bool,
    rejected_labels: list[str] | None = None,
) -> dict[str, object]:
    context = getattr(session, "confirmed_context", {})
    summaries = {
        identifier: template.summary
        for identifier, template in DOMAIN_TEMPLATES.items()
        if identifier != "generic"
    }
    rejected = rejected_labels or []
    return {
        "instruction": (
            "Return one strict JSON object matching HermesTemplateSelection. Here are ten curated template ids "
            "and their one-line summaries; choose the closest template to the user's goal, audience, and desired "
            "outputs, or use template_id 'none' if nothing fits reasonably. Explain the choice in reasoning. You "
            "may optionally rename existing field, section, and metric labels using the corresponding override "
            "dictionaries to match the user's wording. You are forbidden from adding or removing fields, changing "
            "field or section kinds, changing metrics or calculations, or inventing any new structure. Do not choose "
            "an excluded template id."
        ),
        "templates": summaries,
        "user": {
            "goal": context.get("goal", ""),
            "audience": context.get("audience", ""),
            "outputs": context.get("outputs", ""),
        },
        "exclude_template_ids": list(exclude_template_ids),
        "repair_attempt": repair_attempt,
        "rejected_override_labels": [
            {"label": label, "reason": "Sensitive-sounding labels are not permitted in model-proposed display labels."}
            for label in rejected
        ],
    }


def _hermes_template_selection(
    session: object,
    exclude_template_ids: Sequence[str] = (),
) -> tuple[str, DomainTemplate, str | None]:
    client = managed_hermes.client
    if client is None:
        raise RuntimeError("Hermes client is unavailable")

    excluded = set(exclude_template_ids)
    rejected_labels: list[str] = []
    for attempt in range(2):
        message = _template_selection_prompt(
            session,
            tuple(excluded),
            repair_attempt=attempt == 1,
            rejected_labels=rejected_labels,
        )
        try:
            selection = call_hermes_json(client, message, HermesTemplateSelection, timeout=20)
            if selection.template_id not in DOMAIN_TEMPLATES and selection.template_id != "none":
                raise ValueError("Hermes selected an unknown template")
            if selection.template_id in excluded:
                raise ValueError("Hermes selected an excluded template")
        except httpx.HTTPError:
            # A network/transport fault is not a repairable structured-output
            # problem; propagate immediately instead of consuming an attempt.
            raise
        except Exception:
            if attempt == 1:
                raise
            continue

        override_values = [
            *selection.field_label_overrides.values(),
            *selection.section_title_overrides.values(),
            *selection.metric_label_overrides.values(),
        ]
        sensitive = find_sensitive_labels(override_values)
        if sensitive and attempt == 0:
            rejected_labels = sensitive
            continue

        if selection.template_id == "none":
            return "generic", DOMAIN_TEMPLATES["generic"], None

        accepted = {
            "fields": {
                key: value for key, value in selection.field_label_overrides.items()
                if value not in sensitive
            },
            "sections": {
                key: value for key, value in selection.section_title_overrides.items()
                if value not in sensitive
            },
            "metrics": {
                key: value for key, value in selection.metric_label_overrides.items()
                if value not in sensitive
            },
        }
        template = apply_template_overrides(DOMAIN_TEMPLATES[selection.template_id], accepted)
        return selection.template_id, template, selection.reasoning
    raise ValueError("Hermes did not return a valid template selection")


def select_template_for_intake(
    session: object,
    exclude_template_ids: Sequence[str] = (),
) -> tuple[str, DomainTemplate, str | None]:
    """Select a safe curated template, failing open to the generic preview."""

    from dashboard.api.hermes import provider_registry

    # The managed Hermes gateway can be up (client is not None) with zero
    # providers actually configured -- the gateway process itself doesn't
    # need a provider key to start, only to answer a real chat completion.
    # Without this check, a healthy-but-unconfigured gateway would make a
    # real (slow-failing) network call on every first-time dashboard
    # creation instead of failing open immediately like the rest of this
    # function already does for other unavailability cases.
    if managed_hermes.client is None or not any(item.connected for item in provider_registry.list()):
        return "generic", DOMAIN_TEMPLATES["generic"], None
    try:
        return _hermes_template_selection(session, exclude_template_ids)
    except httpx.HTTPError:
        support_events.record(
            "hermes_template_unavailable",
            level="WARNING",
            details={"code": "provider_unavailable", "component": "intake_template"},
        )
    except Exception:
        support_events.record(
            "hermes_template_invalid",
            level="WARNING",
            details={"code": "invalid_template_selection", "component": "intake_template"},
        )
    return "generic", DOMAIN_TEMPLATES["generic"], None


@router.post("", response_model=IntakeResponse, status_code=status.HTTP_201_CREATED)
def start_intake(payload: StartIntakeRequest) -> IntakeResponse:
    return intake_store.start(payload.language)


@router.post("/{session_id}/answers", response_model=IntakeResponse)
def answer_intake(session_id: UUID, payload: IntakeAnswerRequest) -> IntakeResponse:
    try:
        return intake_store.answer(session_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Intake session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{session_id}", response_model=IntakeResponse)
def reopen_intake(session_id: UUID) -> IntakeResponse:
    try:
        return intake_store.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Intake session not found") from exc


@router.get("/{session_id}/preview", response_model=IntakeWorkspacePreview)
def intake_preview(session_id: UUID) -> IntakeWorkspacePreview:
    try:
        response = intake_store.get(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Intake session not found") from exc
    if response.step.value != "complete":
        raise HTTPException(status_code=409, detail="Complete intake before generating a preview")

    stored_template_id = intake_store.get_resource(session_id, "_template_id")
    if stored_template_id in DOMAIN_TEMPLATES:
        template_id = stored_template_id
        template = DOMAIN_TEMPLATES[template_id]
        reasoning = intake_store.get_resource(session_id, "_template_reasoning") or None
        selection = (template_id, template, reasoning)
    else:
        selection = select_template_for_intake(response)
        template_id, _, reasoning = selection
        intake_store.set_resource(session_id, "_template_id", template_id)
        intake_store.set_resource(session_id, "_template_attempts", "1")
        intake_store.set_resource(session_id, "_template_reasoning", reasoning or "")
    return _build_intake_preview(session_id, selection)


def _build_intake_preview(
    session_id: UUID,
    selection: tuple[str, DomainTemplate, str | None],
) -> IntakeWorkspacePreview:
    response = intake_store.get(session_id)
    language = response.language.value
    title = response.confirmed_context.get("goal", "Dashboard")[:120]
    saved_draft = intake_store.get_resource(session_id, "_draft")
    draft_options = PreviewDraft.model_validate_json(saved_draft) if saved_draft else None
    terminology = draft_options.terminology if draft_options else {}
    requested_outputs = response.confirmed_context.get("outputs", "web").casefold()
    enabled_outputs = [
        output for marker, output in (("web", OutputKind.WEB), ("excel", OutputKind.EXCEL), ("xlsx", OutputKind.EXCEL), ("pdf", OutputKind.PDF))
        if marker in requested_outputs
    ]
    enabled_outputs = list(dict.fromkeys(enabled_outputs)) or [OutputKind.WEB]

    template_id, selected_template, reasoning = selection
    if template_id == "generic":
        template = build_generic_template(
            language=language,
            terminology=terminology,
            chart_type=draft_options.chart_type if draft_options else "bar",
            section_order=draft_options.section_order if draft_options else ("summary", "distribution", "details"),
        )
    else:
        fields = [
            item.model_copy(update={"label": terminology.get(item.id, item.label)})
            if item.id in terminology and terminology[item.id].strip()
            else item
            for item in selected_template.fields
        ]
        section_order = draft_options.section_order if draft_options else ["summary", "distribution", "details"]
        order_index = {identifier: index for index, identifier in enumerate(section_order)}
        sections = [item.model_copy(update={"order": order_index.get(item.id, item.order)}) for item in selected_template.sections]
        visualizations = [
            item.model_copy(update={"kind": VisualizationKind(draft_options.chart_type if draft_options else "bar")})
            for item in selected_template.visualizations
        ]
        template = selected_template.model_copy(update={"fields": fields, "sections": sections, "visualizations": visualizations})

    fields = template.fields
    spec = DashboardSpec(
        id=f"intake-{session_id}", title=title, fields=fields,
        mappings=[FieldMapping(source_field=item.id, target_field=item.id, approved=True) for item in fields],
        metrics=template.metrics,
        visualizations=template.visualizations,
        sections=template.sections,
        layout=LayoutSpec(), localization=LocalizationSpec(language=language, locale="pt-BR" if language == "pt" else "en-US", timezone="America/Sao_Paulo" if language == "pt" else "UTC"),
        privacy=PrivacyPolicy(), outputs=OutputSpec(enabled=enabled_outputs),
        terminology=terminology,
        style=StyleSpec(palette=[draft_options.accent_color if draft_options else "#1D4ED8"]),
    )
    records = [{"group": f"{fields[0].label} {((index - 1) % 5) + 1}", "value": 100 + ((index * 173) % 900)} for index in range(1, 19)]
    document = build_report_document(spec, records, synthetic=True)
    draft = DraftDashboardSchema(
        source_format="guided-intake",
        fields=[ProposedField(id=item.id, display_name=item.label, inferred_type=FieldType.NUMBER if item.kind is FieldKind.NUMBER else FieldType.TEXT, confidence=Confidence.MEDIUM, evidence=["Guided intake synthetic preview"]) for item in fields],
        sections=[ProposedSection(id=item.id, display_name=item.title, source_section="guided-intake", presentation=item.kind.value, confidence=Confidence.MEDIUM) for item in spec.sections],
        assumptions=["This structure uses synthetic data and remains a draft until every section is approved."],
    )
    stored = intake_store.get_resource(session_id, "_approval_id")
    try:
        approval = approval_store.get(UUID(stored)) if stored else None
    except (KeyError, ValueError):
        approval = None
    if approval is None:
        approval = approval_store.create(CreateApprovalRequest(draft_schema=draft, dependencies={"distribution": ["summary"], "details": ["summary"]}))
        intake_store.set_resource(session_id, "_approval_id", str(approval.approval_id))
    linked_project = intake_store.get_resource(session_id, "_project_id")
    return IntakeWorkspacePreview(
        document=document,
        approval=approval,
        project_id=UUID(linked_project) if linked_project else None,
        template_id=template_id if template_id != "generic" else None,
        template_reasoning=reasoning if template_id != "generic" else None,
    )


@router.post("/{session_id}/retry-template", response_model=IntakeWorkspacePreview)
def retry_intake_template(session_id: UUID) -> IntakeWorkspacePreview:
    try:
        response = intake_store.get(session_id)
        attempts_raw = intake_store.get_resource(session_id, "_template_attempts") or "0"
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Intake session not found") from exc
    if response.step.value != "complete":
        raise HTTPException(status_code=409, detail="Complete intake before generating a preview")
    try:
        attempts = int(attempts_raw)
    except ValueError:
        attempts = 0
    if attempts >= 2:
        raise HTTPException(status_code=409, detail="No more template attempts remain")

    previous_id = intake_store.get_resource(session_id, "_template_id")
    excluded = [previous_id] if previous_id and previous_id != "generic" else []
    selection = select_template_for_intake(response, exclude_template_ids=excluded)
    template_id, _, reasoning = selection
    intake_store.set_resource(session_id, "_template_attempts", str(attempts + 1))
    intake_store.set_resource(session_id, "_template_id", template_id)
    intake_store.set_resource(session_id, "_template_reasoning", reasoning or "")
    intake_store.set_resource(session_id, "_approval_id", "")
    return _build_intake_preview(session_id, selection)


@router.post("/{session_id}/project-link", status_code=204)
def link_intake_project(session_id: UUID, payload: IntakeProjectLinkRequest) -> None:
    try:
        project_repository.get(payload.project_id)
        intake_store.set_resource(session_id, "_project_id", str(payload.project_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Intake session or project not found") from exc


@router.get("/{session_id}/draft", response_model=PreviewDraft | None)
def get_intake_draft(session_id: UUID):
    try:
        raw = intake_store.get_resource(session_id, "_draft")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Intake session not found") from exc
    return PreviewDraft.model_validate_json(raw) if raw else None


@router.post("/{session_id}/draft", response_model=PreviewDraft, status_code=201)
def create_intake_draft(session_id: UUID, payload: PreviewDraftRequest) -> PreviewDraft:
    try:
        intake_store.get(session_id)
        previous = intake_store.get_resource(session_id, "_draft")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Intake session not found") from exc
    if payload.feedback:
        if not payload.feedback_non_confidential:
            raise HTTPException(status_code=409, detail="Confirm the feedback is non-confidential before sending it to Hermes")
        try:
            safe_memory_store.remember(kind=MemoryKind.FEEDBACK, key="preview_feedback", value=payload.feedback)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="Feedback appears confidential and was not sent to Hermes") from exc
        from dashboard.api.hermes import provider_registry
        from automation.agent.models import ProviderName

        codex = provider_registry.get(ProviderName.CODEX)
        if codex is not None and (not codex.connected or codex.model != "gpt-5.5"):
            raise HTTPException(status_code=409, detail={
                "code": "provider_model_incompatible",
                "message": "The connected Codex provider is not ready for gpt-5.5. Reconnect Codex before retrying.",
                "fields": [{"field": "provider", "message": "Expected openai-codex with gpt-5.5."}],
            })
        client = managed_hermes.client
        if client is None:
            raise HTTPException(status_code=503, detail={
                "code": "provider_not_ready",
                "message": "Hermes is not ready. Connect an AI provider and try again.",
                "fields": [{"field": "provider", "message": "Choose a provider and connect its API key."}],
            })
        original_feedback = payload.feedback
        allowed_sections = {"summary", "distribution", "details"}
        for attempt in range(2):
            try:
                message = {
                    "instruction": "Return one strict JSON object with accent_color, chart_type, section_order, terminology, and reasoning only. Include every section exactly once. reasoning is a short, plain-language explanation (max 400 characters) of what you changed and why, addressed to the user.",
                    "feedback": payload.feedback,
                    "current": payload.model_dump(exclude={"feedback"}),
                    "required_sections": sorted(allowed_sections),
                    "repair_attempt": attempt == 1,
                }
                try:
                    proposed_raw = call_hermes_json(client, message, HermesDraftProposal)
                except httpx.HTTPError as exc:
                    support_events.record("hermes_provider_unavailable", level="WARNING", details={"code": "provider_unavailable", "component": "review"})
                    raise HTTPException(status_code=503, detail={
                        "code": "provider_unavailable",
                        "message": "No working AI provider is available. Connect a provider in this review screen and try again.",
                        "fields": [{"field": "provider", "message": "Check the API key, provider access, and network connection."}],
                    }) from exc
                if set(proposed_raw.section_order) != allowed_sections or len(proposed_raw.section_order) != len(allowed_sections):
                    raise ValueError("Invalid reviewed section order")
                payload = PreviewDraftRequest(
                    accent_color=proposed_raw.accent_color, chart_type=proposed_raw.chart_type,
                    section_order=proposed_raw.section_order, terminology=proposed_raw.terminology,
                )
                reasoning = proposed_raw.reasoning
                hermes_applied = True
                break
            except HTTPException:
                # Provider/runtime failures already carry actionable status and
                # must not be mistaken for repairable structured JSON.
                raise
            except Exception as exc:
                if attempt == 1:
                    support_events.record("hermes_draft_invalid", level="WARNING", details={"attempt": 2, "code": "invalid_hermes_draft", "component": "review"})
                    raise HTTPException(status_code=422, detail={
                        "code": "invalid_hermes_draft",
                        "message": "Hermes could not produce a valid dashboard revision after one retry. The active specification was not changed.",
                        "fields": [{"field": "feedback", "message": "Revise the request and try again."}],
                    }) from exc
    else:
        hermes_applied = False
        reasoning = None
        original_feedback = None
    allowed_sections = {"summary", "distribution", "details"}
    if set(payload.section_order) != allowed_sections or len(payload.section_order) != len(allowed_sections):
        raise HTTPException(status_code=409, detail="Draft section order must contain every reviewed section exactly once")
    try:
        for key, value in payload.terminology.items():
            safe_memory_store.remember(kind=MemoryKind.PROJECT_TERMINOLOGY, key=key, value=value)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Draft terminology appears confidential and was not persisted") from exc
    previous_draft = PreviewDraft.model_validate_json(previous) if previous else None
    version = previous_draft.version + 1 if previous_draft else 1
    history = list(previous_draft.feedback_history) if previous_draft else []
    if hermes_applied and reasoning and original_feedback:
        history.append(FeedbackTurn(feedback=original_feedback, reasoning=reasoning, version=version))
        history = history[-20:]
    draft = PreviewDraft(
        version=version, accent_color=payload.accent_color, chart_type=payload.chart_type,
        section_order=payload.section_order, terminology=payload.terminology,
        feedback_applied_by_hermes=hermes_applied, feedback_reasoning=reasoning,
        feedback_history=history,
    )
    intake_store.set_resource(session_id, "_draft", draft.model_dump_json())
    # Any structural/design change starts a fresh review package.  The active
    # approved project specification, if one exists, remains untouched.
    intake_store.set_resource(session_id, "_approval_id", "")
    return draft


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def discard_intake(session_id: UUID) -> None:
    try:
        intake_store.discard(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Intake session not found") from exc


__all__ = [
    "router",
    "IntakeWorkspacePreview",
    "PreviewDraft",
    "PreviewDraftRequest",
    "FeedbackTurn",
    "HermesTemplateSelection",
    "HermesDraftProposal",
    "IntakeProjectLinkRequest",
    "select_template_for_intake",
]
