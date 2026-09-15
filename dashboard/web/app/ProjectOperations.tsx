"use client";

import { useState } from "react";

type Props = { language: "en" | "pt"; projectId: string; projectDirectory: string; outputs: string[]; fields: Field[]; activeSpecificationVersion?: number; projectNonConfidential?: boolean; onSpecificationActivated?: (specification: ProjectSpecification, version: number) => void };
type Field = { id: string; label: string };
type ProjectSpecification = { title: string; fields: Field[]; outputs: { enabled: string[] } };
type Inspection = { id: string; inspection: { fields: Array<{ path: string; name: string; type: string }>; mappings: Array<{ source_path: string; target_field: string | null }> } };
type ImportInspection = { id: string; plan: { mappings: Array<{ source_column: string; target_field: string | null }>; sources: Array<{ columns: string[]; likely_confidential_columns: string[] }> } };
type Diagnostics = { diagnostic_id: string; ok: boolean; components: Record<string, { ok: boolean; remediation: string | null }>; checks: Array<{ name: string; ok: boolean; detail: string; remediation: string | null }> };
type Approval = { approval_id: string; ready_to_activate: boolean; sections: Record<string, { section_id: string; status: "pending" | "approved" | "rejected" | "blocked" }> };
type Revision = { id: string; base_version: number; mode: "update" | "recreate"; hermes_response: string; active_specification_unchanged: boolean; specification: ProjectSpecification & { sections: Array<{ id: string; title: string; kind: string }>; style: { palette: string[] } }; approval: Approval; preview: { synthetic: boolean; metrics: Record<string, number | null> } };
type ActivatedWorkspace = { project: { active_specification_version: number }; specification: ProjectSpecification };

const copy = {
  en: { title: "Project operations", updateDashboard: "Update dashboard with Hermes", updateHelp: "Describe the presentation change. Hermes receives the approved specification and your non-confidential instruction, never source records.", instruction: "What should Hermes change?", instructionSafe: "I confirm this instruction is non-confidential", askUpdate: "Ask Hermes to update", askRecreate: "Ask Hermes to re-create", hermesResponse: "Hermes response", revisionReady: "Hermes created a synthetic revision draft. The active dashboard is unchanged.", activeUnchanged: "Active dashboard unchanged", syntheticRevision: "Synthetic revision preview", approveSection: "Approve section", rejectSection: "Reject section", activationSafe: "I confirm this project's persisted data is non-confidential", activateRevision: "Activate approved revision", returnProject: "Return to project", source: "JSON API source", inspect: "Save and inspect source", approve: "Approve mappings and classifications", sync: "Synchronize now", endpoint: "HTTPS endpoint", sample: "Representative JSON", importing: "CSV/XLSX import", path: "Local file or folder", inspectImport: "Inspect import", approveImport: "Approve import summary", applyImport: "Apply approved import", reports: "Reports", destination: "Approved local output folder", generate: "Generate selected reports", schedule: "Local schedule", preview: "Preview schedule", activate: "Activate schedule explicitly", history: "Refresh run history", safe: "I confirm the project and source are non-confidential", status: "Status", formats: "Imports support CSV and XLSX. Reports support web, Excel, and PDF.", error: "The operation failed. Review the guidance and try again.", diagnostics: "Diagnostics", refreshDiagnostics: "Refresh diagnostics", downloadSupport: "Download sanitized support bundle", copyDiagnostic: "Copy diagnostic ID" },
  pt: { title: "Operações do projeto", updateDashboard: "Atualizar dashboard com o Hermes", updateHelp: "Descreva a mudança de apresentação. O Hermes recebe a especificação aprovada e sua instrução não confidencial, nunca os registros da fonte.", instruction: "O que o Hermes deve alterar?", instructionSafe: "Confirmo que esta instrução não é confidencial", askUpdate: "Pedir ao Hermes para atualizar", askRecreate: "Pedir ao Hermes para recriar", hermesResponse: "Resposta do Hermes", revisionReady: "O Hermes criou um rascunho sintético. O dashboard ativo não foi alterado.", activeUnchanged: "Dashboard ativo não alterado", syntheticRevision: "Prévia sintética da revisão", approveSection: "Aprovar seção", rejectSection: "Rejeitar seção", activationSafe: "Confirmo que os dados persistidos deste projeto não são confidenciais", activateRevision: "Ativar revisão aprovada", returnProject: "Voltar ao projeto", source: "Fonte de API JSON", inspect: "Salvar e inspecionar fonte", approve: "Aprovar mapeamentos e classificações", sync: "Sincronizar agora", endpoint: "Endpoint HTTPS", sample: "JSON representativo", importing: "Importação CSV/XLSX", path: "Arquivo ou pasta local", inspectImport: "Inspecionar importação", approveImport: "Aprovar resumo da importação", applyImport: "Aplicar importação aprovada", reports: "Relatórios", destination: "Pasta local aprovada para saída", generate: "Gerar relatórios selecionados", schedule: "Agendamento local", preview: "Visualizar agenda", activate: "Ativar agenda explicitamente", history: "Atualizar histórico", safe: "Confirmo que o projeto e a fonte não são confidenciais", status: "Status", formats: "Importações aceitam CSV e XLSX. Relatórios aceitam web, Excel e PDF.", error: "A operação falhou. Revise a orientação e tente novamente.", diagnostics: "Diagnósticos", refreshDiagnostics: "Atualizar diagnósticos", downloadSupport: "Baixar pacote de suporte sanitizado", copyDiagnostic: "Copiar ID do diagnóstico" },
};

function errorDetail(value: unknown, fallback: string): string {
  if (typeof value === "string") return value;
  if (value && typeof value === "object") {
    const detail = value as { message?: string; fields?: Array<{ field?: string; message?: string }> };
    if (detail.fields?.length) return detail.fields.map((item) => `${item.field ?? "request"}: ${item.message ?? fallback}`).join(" · ");
    if (detail.message) return detail.message;
  }
  return fallback;
}

class RequestError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request(path: string, init?: RequestInit) {
  const response = await fetch(`/backend${path}`, { ...init, cache: "no-store" });
  const value = response.status === 204 ? null : await response.json();
  if (!response.ok) throw new RequestError(errorDetail(value?.detail, `HTTP ${response.status}`), response.status);
  return value;
}

export default function ProjectOperations({ language, projectId, projectDirectory, outputs, fields, activeSpecificationVersion = 1, projectNonConfidential = true, onSpecificationActivated = () => undefined }: Props) {
  const t = copy[language];
  const [endpoint, setEndpoint] = useState("");
  const [sample, setSample] = useState('{"items":[{"group":"A","value":10}]}');
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [approvalId, setApprovalId] = useState("");
  const [importPath, setImportPath] = useState("");
  const [importSummary, setImportSummary] = useState<ImportInspection | null>(null);
  const [importApprovalId, setImportApprovalId] = useState("");
  const [revisionInstruction, setRevisionInstruction] = useState("");
  const [revisionInstructionSafe, setRevisionInstructionSafe] = useState(false);
  const [revision, setRevision] = useState<Revision | null>(null);
  const [revisionOpen, setRevisionOpen] = useState(false);
  const [revisionActivationSafe, setRevisionActivationSafe] = useState(false);
  const [destination, setDestination] = useState(projectDirectory);
  const [nonConfidential, setNonConfidential] = useState(false);
  const [scheduleId, setScheduleId] = useState("");
  const [history, setHistory] = useState<object | null>(null);
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const [status, setStatus] = useState(t.formats);
  const [busy, setBusy] = useState(false);

  const run = async (work: () => Promise<unknown>) => {
    setBusy(true);
    try { const result = await work(); setStatus(typeof result === "string" ? result : JSON.stringify(result, null, 2)); }
    catch (problem) { setStatus(problem instanceof Error ? problem.message : t.error); }
    finally { setBusy(false); }
  };
  const sourceId = "primary-api";
  const saveAndInspect = () => run(async () => {
    const source = { id: sourceId, name: "Primary API", endpoint, auth_method: "none", records_path: null, pagination: { kind: "none" }, timeout_seconds: 20, max_retries: 3, backoff_seconds: 0.25, incremental_confirmed: false };
    await request(`/api/api-sources/${sourceId}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: projectId, source }) });
    const target_fields = Object.fromEntries(fields.map((field) => [field.id, field.label]));
    const result = await request("/api/api-sources/inspect", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: projectId, source_id: sourceId, representative_json: JSON.parse(sample), target_fields }) }) as Inspection;
    setInspection(result); return result;
  });
  const approveSource = () => run(async () => {
    if (!inspection) throw new Error(t.inspect);
    const mappings = Object.fromEntries(inspection.inspection.mappings.filter((item) => fields.some((field) => field.id === item.target_field)).map((item) => [item.source_path, item.target_field]));
    const field_classifications = Object.fromEntries(inspection.inspection.fields.map((field) => [field.path, false]));
    const result = await request("/api/api-sources/approve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: projectId, source_id: sourceId, inspection_id: inspection.id, mappings, field_classifications, approved_by: "local-user" }) });
    setApprovalId(result.id); return result;
  });
  const sync = () => run(() => request("/api/api-sources/sync", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: projectId, source_id: sourceId, inspection_id: inspection?.id, approval_id: approvalId, mode: "full" }) }));
  const inspectImport = () => run(async () => { const value = await request("/api/imports/inspect", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: projectId, location: importPath }) }) as ImportInspection; setImportSummary(value); return value; });
  const approveImport = () => run(async () => {
    if (!importSummary) throw new Error(t.inspectImport);
    const mappings = Object.fromEntries(importSummary.plan.mappings.filter((item) => item.target_field).map((item) => [item.source_column, item.target_field]));
    const columns = [...new Set(importSummary.plan.sources.flatMap((item) => item.columns))];
    const detected = new Set(importSummary.plan.sources.flatMap((item) => item.likely_confidential_columns));
    const field_classifications = Object.fromEntries(columns.map((column) => [column, detected.has(column)]));
    const value = await request("/api/imports/approve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: projectId, inspection_id: importSummary.id, mode: "replace", mappings, relationships_confirmed: true, field_classifications, classification_overrides: {}, permit_persistence: false, approved_by: "local-user" }) });
    setImportApprovalId(value.id); return value;
  });
  const applyImport = () => run(() => request("/api/imports/apply", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: projectId, inspection_id: importSummary?.id, approval_id: importApprovalId }) }));
  const requestRevision = (mode: "update" | "recreate") => run(async () => {
    const value = await request(`/api/projects/${projectId}/revisions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ instruction: revisionInstruction, instruction_non_confidential: revisionInstructionSafe, mode }) }) as Revision;
    setRevision(value); return t.revisionReady;
  });
  const decideRevision = (sectionId: string, approve: boolean) => run(async () => {
    if (!revision) return null;
    const approval = await request(`/api/approvals/${revision.approval.approval_id}/sections/${sectionId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approve, feedback: null }) }) as Approval;
    setRevision({ ...revision, approval }); return t.revisionReady;
  });
  const activateRevision = () => run(async () => {
    if (!revision) return null;
    const value = await request(`/api/projects/${projectId}/revisions/${revision.id}/activate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approved_by: "local-user", confirmed_non_confidential: projectNonConfidential || revisionActivationSafe }) }) as ActivatedWorkspace;
    onSpecificationActivated(value.specification, value.project.active_specification_version);
    setRevision(null); setRevisionInstruction(""); setRevisionInstructionSafe(false); setRevisionOpen(false); setRevisionActivationSafe(false);
    return language === "pt" ? "Revisão ativada." : "Revision activated.";
  });
  const returnToProject = () => {
    setRevision(null); setRevisionOpen(false);
    document.getElementById("current-project-title")?.scrollIntoView({ behavior: "smooth" });
  };
  const generate = () => run(() => request("/api/reports", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: projectId, specification_version: activeSpecificationVersion, outputs, filter_values: {}, non_confidential_destination: destination }) }));
  const previewSchedule = () => run(() => request("/api/schedules/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ schedule: { id: scheduleId || "local-daily", project_id: projectId, project_directory: projectDirectory, name: "Daily reports", frequency: "daily", timezone: "America/Sao_Paulo", hour: 9, minute: 0, output_directory: destination, outputs, retention_limit: 10, project_non_confidential_confirmed: nonConfidential, source_non_confidential_confirmed: nonConfidential, approval_confirmed: false, enabled: false }, count: 5 }) }));
  const activateSchedule = () => run(async () => {
    if (!nonConfidential) throw new Error(t.safe);
    const id = scheduleId || "local-daily";
    try { await request("/api/schedules", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, project_id: projectId, project_directory: projectDirectory, name: "Daily reports", frequency: "daily", timezone: "America/Sao_Paulo", hour: 9, minute: 0, output_directory: destination, outputs, retention_limit: 10, project_non_confidential_confirmed: true, source_non_confidential_confirmed: true, approval_confirmed: false, enabled: false }) }); } catch (problem) { if (!(problem instanceof RequestError && problem.status === 409)) throw problem; /* 409 means a definition already exists; it is activated below */ }
    const value = await request(`/api/schedules/${id}/activate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approved_by: "local-user" }) }); setScheduleId(id); return value;
  });
  const refreshDiagnostics = () => run(async () => { const value = await request("/api/diagnostics") as Diagnostics; setDiagnostics(value); return value; });
  const downloadSupport = () => run(async () => {
    const response = await fetch("/backend/api/diagnostics/support-bundle", { method: "POST" });
    if (!response.ok) throw new Error(t.error);
    const blob = await response.blob(); const url = URL.createObjectURL(blob);
    const link = document.createElement("a"); link.href = url; link.download = `dashboard-support-${response.headers.get("X-Diagnostic-Id") ?? "local"}.zip`;
    document.body.appendChild(link); link.click(); link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0); return t.downloadSupport;
  });

  return <section className="operations" aria-labelledby="operations-title"><h2 id="operations-title">{t.title}</h2><p>{t.formats}</p>
    <details open={revisionOpen} onToggle={(event) => setRevisionOpen(event.currentTarget.open)}><summary>{t.updateDashboard}</summary><p>{t.updateHelp}</p><label>{t.instruction}<textarea rows={4} value={revisionInstruction} onChange={(event) => setRevisionInstruction(event.target.value)} /></label><label><input type="checkbox" checked={revisionInstructionSafe} onChange={(event) => setRevisionInstructionSafe(event.target.checked)} /> {t.instructionSafe}</label><div className="revision-actions"><button disabled={busy || !revisionInstruction.trim() || !revisionInstructionSafe} onClick={() => requestRevision("update")}>{t.askUpdate}</button><button disabled={busy || !revisionInstruction.trim() || !revisionInstructionSafe} onClick={() => requestRevision("recreate")}>{t.askRecreate}</button></div>{revision && <div className="revision-preview"><section className="hermes-response" aria-live="polite"><strong>{t.hermesResponse}</strong><p>{revision.hermes_response}</p></section><div className="revision-preview-heading"><div><span className="status revision">{t.syntheticRevision}</span><h3>{revision.specification.title}</h3><p>{t.activeUnchanged} · v{revision.base_version}</p></div><button onClick={returnToProject}>{t.returnProject}</button></div><div className="revision-metrics">{Object.entries(revision.preview.metrics).map(([name, value]) => <div key={name}><span>{name}</span><strong>{value ?? "—"}</strong></div>)}</div>{revision.specification.sections.map((section) => { const decision = revision.approval.sections[section.id]; return <article key={section.id}><div><strong>{section.title}</strong><span>{section.kind}</span></div><span className={`status ${decision?.status === "approved" ? "approved" : "revision"}`}>{decision?.status ?? "pending"}</span><button disabled={busy || decision?.status === "blocked"} onClick={() => decideRevision(section.id, true)}>{t.approveSection}</button><button disabled={busy || decision?.status === "blocked"} onClick={() => decideRevision(section.id, false)}>{t.rejectSection}</button></article>; })}{revision.approval.ready_to_activate && <div className="revision-activation">{!projectNonConfidential && <label><input type="checkbox" checked={revisionActivationSafe} onChange={(event) => setRevisionActivationSafe(event.target.checked)} /> {t.activationSafe}</label>}<button className="primary" disabled={busy || (!projectNonConfidential && !revisionActivationSafe)} onClick={activateRevision}>{t.activateRevision}</button></div>}</div>}</details>
    <details open><summary>{t.source}</summary><label>{t.endpoint}<input value={endpoint} onChange={(event) => setEndpoint(event.target.value)} placeholder="https://api.example.com/records" /></label><label>{t.sample}<textarea value={sample} onChange={(event) => setSample(event.target.value)} rows={4} /></label><button disabled={busy || !endpoint} onClick={saveAndInspect}>{t.inspect}</button><button disabled={busy || !inspection} onClick={approveSource}>{t.approve}</button><button disabled={busy || !approvalId} onClick={sync}>{t.sync}</button></details>
    <details><summary>{t.importing}</summary><label>{t.path}<input value={importPath} onChange={(event) => setImportPath(event.target.value)} /></label><button disabled={busy || !importPath} onClick={inspectImport}>{t.inspectImport}</button><button disabled={busy || !importSummary} onClick={approveImport}>{t.approveImport}</button><button disabled={busy || !importApprovalId} onClick={applyImport}>{t.applyImport}</button>{importSummary && <pre>{JSON.stringify(importSummary, null, 2)}</pre>}</details>
    <details><summary>{t.reports}</summary><label>{t.destination}<input value={destination} onChange={(event) => setDestination(event.target.value)} /></label><button disabled={busy || !approvalId || !destination} onClick={generate}>{t.generate}</button></details>
    <details><summary>{t.schedule}</summary><label><input type="checkbox" checked={nonConfidential} onChange={(event) => setNonConfidential(event.target.checked)} /> {t.safe}</label><button disabled={busy || !destination} onClick={previewSchedule}>{t.preview}</button><button disabled={busy || !nonConfidential} onClick={activateSchedule}>{t.activate}</button><button disabled={busy || !scheduleId} onClick={() => run(async () => { const value = await request(`/api/schedules/${scheduleId}/runs`); setHistory(value); return value; })}>{t.history}</button>{history && <pre>{JSON.stringify(history, null, 2)}</pre>}</details>
    <details><summary>{t.diagnostics}</summary><button disabled={busy} onClick={refreshDiagnostics}>{t.refreshDiagnostics}</button><button disabled={busy} onClick={downloadSupport}>{t.downloadSupport}</button>{diagnostics && <><p><code>{diagnostics.diagnostic_id}</code> <button onClick={() => void navigator.clipboard.writeText(diagnostics.diagnostic_id)}>{t.copyDiagnostic}</button></p><div className="diagnostic-grid">{Object.entries(diagnostics.components).map(([name, component]) => <div key={name}><strong>{name}</strong><span className={`status ${component.ok ? "approved" : "revision"}`}>{component.ok ? "OK" : "Attention"}</span>{!component.ok && component.remediation && <p>{component.remediation}</p>}</div>)}</div></>}</details>
    <h3>{t.status}</h3><pre aria-live="polite">{status}</pre>
  </section>;
}
