"use client";

import { useState } from "react";

type Props = { language: "en" | "pt"; projectId: string; projectDirectory: string; outputs: string[]; fields: Field[] };
type Field = { id: string; label: string };
type Inspection = { id: string; inspection: { fields: Array<{ path: string; name: string; type: string }>; mappings: Array<{ source_path: string; target_field: string | null }> } };
type ImportInspection = { id: string; plan: { mappings: Array<{ source_column: string; target_field: string | null }>; sources: Array<{ columns: string[]; likely_confidential_columns: string[] }> } };

const copy = {
  en: { title: "Project operations", source: "JSON API source", inspect: "Save and inspect source", approve: "Approve mappings and classifications", sync: "Synchronize now", endpoint: "HTTPS endpoint", sample: "Representative JSON", importing: "CSV/XLSX import", path: "Local file or folder", inspectImport: "Inspect import", approveImport: "Approve import summary", applyImport: "Apply approved import", provider: "Provider setup", key: "API key (sent directly to the OS keyring)", connect: "Connect provider", reports: "Reports", destination: "Approved local output folder", generate: "Generate selected reports", schedule: "Local schedule", preview: "Preview schedule", activate: "Activate schedule explicitly", history: "Refresh run history", safe: "I confirm the project and source are non-confidential", status: "Status", formats: "Imports support CSV and XLSX. Reports support web, Excel, and PDF.", error: "The operation failed. Review the guidance and try again." },
  pt: { title: "Operações do projeto", source: "Fonte de API JSON", inspect: "Salvar e inspecionar fonte", approve: "Aprovar mapeamentos e classificações", sync: "Sincronizar agora", endpoint: "Endpoint HTTPS", sample: "JSON representativo", importing: "Importação CSV/XLSX", path: "Arquivo ou pasta local", inspectImport: "Inspecionar importação", approveImport: "Aprovar resumo da importação", applyImport: "Aplicar importação aprovada", provider: "Configuração de provedor", key: "Chave de API (enviada diretamente ao cofre do sistema)", connect: "Conectar provedor", reports: "Relatórios", destination: "Pasta local aprovada para saída", generate: "Gerar relatórios selecionados", schedule: "Agendamento local", preview: "Visualizar agenda", activate: "Ativar agenda explicitamente", history: "Atualizar histórico", safe: "Confirmo que o projeto e a fonte não são confidenciais", status: "Status", formats: "Importações aceitam CSV e XLSX. Relatórios aceitam web, Excel e PDF.", error: "A operação falhou. Revise a orientação e tente novamente." },
};

async function request(path: string, init?: RequestInit) {
  const response = await fetch(`/backend${path}`, { ...init, cache: "no-store" });
  const value = response.status === 204 ? null : await response.json();
  if (!response.ok) throw new Error(value?.detail ?? `HTTP ${response.status}`);
  return value;
}

export default function ProjectOperations({ language, projectId, projectDirectory, outputs, fields }: Props) {
  const t = copy[language];
  const [endpoint, setEndpoint] = useState("");
  const [sample, setSample] = useState('{"items":[{"group":"A","value":10}]}');
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [approvalId, setApprovalId] = useState("");
  const [importPath, setImportPath] = useState("");
  const [importSummary, setImportSummary] = useState<ImportInspection | null>(null);
  const [importApprovalId, setImportApprovalId] = useState("");
  const [provider, setProvider] = useState("gemini");
  const [apiKey, setApiKey] = useState("");
  const [destination, setDestination] = useState(projectDirectory);
  const [nonConfidential, setNonConfidential] = useState(false);
  const [scheduleId, setScheduleId] = useState("");
  const [history, setHistory] = useState<object | null>(null);
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
  const connectProvider = () => run(async () => {
    const value = await request("/api/providers/connect-api-key", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: projectId, provider, account_id: "local", model: `${provider}-default`, api_key: apiKey, capabilities: ["conversation", "structured_output", "insights"] }) });
    setApiKey(""); return value;
  });
  const generate = () => run(() => request("/api/reports", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: projectId, specification_version: 1, outputs, filter_values: {}, non_confidential_destination: destination }) }));
  const previewSchedule = () => run(() => request("/api/schedules/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ schedule: { id: scheduleId || "local-daily", project_id: projectId, project_directory: projectDirectory, name: "Daily reports", frequency: "daily", timezone: "America/Sao_Paulo", hour: 9, minute: 0, output_directory: destination, outputs, retention_limit: 10, project_non_confidential_confirmed: nonConfidential, source_non_confidential_confirmed: nonConfidential, approval_confirmed: false, enabled: false }, count: 5 }) }));
  const activateSchedule = () => run(async () => {
    if (!nonConfidential) throw new Error(t.safe);
    const id = scheduleId || "local-daily";
    try { await request("/api/schedules", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id, project_id: projectId, project_directory: projectDirectory, name: "Daily reports", frequency: "daily", timezone: "America/Sao_Paulo", hour: 9, minute: 0, output_directory: destination, outputs, retention_limit: 10, project_non_confidential_confirmed: true, source_non_confidential_confirmed: true, approval_confirmed: false, enabled: false }) }); } catch { /* an existing definition is activated below */ }
    const value = await request(`/api/schedules/${id}/activate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approved_by: "local-user" }) }); setScheduleId(id); return value;
  });

  return <section className="operations" aria-labelledby="operations-title"><h2 id="operations-title">{t.title}</h2><p>{t.formats}</p>
    <details open><summary>{t.source}</summary><label>{t.endpoint}<input value={endpoint} onChange={(event) => setEndpoint(event.target.value)} placeholder="https://api.example.com/records" /></label><label>{t.sample}<textarea value={sample} onChange={(event) => setSample(event.target.value)} rows={4} /></label><button disabled={busy || !endpoint} onClick={saveAndInspect}>{t.inspect}</button><button disabled={busy || !inspection} onClick={approveSource}>{t.approve}</button><button disabled={busy || !approvalId} onClick={sync}>{t.sync}</button></details>
    <details><summary>{t.importing}</summary><label>{t.path}<input value={importPath} onChange={(event) => setImportPath(event.target.value)} /></label><button disabled={busy || !importPath} onClick={inspectImport}>{t.inspectImport}</button><button disabled={busy || !importSummary} onClick={approveImport}>{t.approveImport}</button><button disabled={busy || !importApprovalId} onClick={applyImport}>{t.applyImport}</button>{importSummary && <pre>{JSON.stringify(importSummary, null, 2)}</pre>}</details>
    <details><summary>{t.provider}</summary><select value={provider} onChange={(event) => setProvider(event.target.value)}><option value="claude">Claude</option><option value="gemini">Gemini</option><option value="deepseek">DeepSeek</option></select><label>{t.key}<input type="password" value={apiKey} autoComplete="off" onChange={(event) => setApiKey(event.target.value)} /></label><button disabled={busy || !apiKey} onClick={connectProvider}>{t.connect}</button></details>
    <details><summary>{t.reports}</summary><label>{t.destination}<input value={destination} onChange={(event) => setDestination(event.target.value)} /></label><button disabled={busy || !approvalId || !destination} onClick={generate}>{t.generate}</button></details>
    <details><summary>{t.schedule}</summary><label><input type="checkbox" checked={nonConfidential} onChange={(event) => setNonConfidential(event.target.checked)} /> {t.safe}</label><button disabled={busy || !destination} onClick={previewSchedule}>{t.preview}</button><button disabled={busy || !nonConfidential} onClick={activateSchedule}>{t.activate}</button><button disabled={busy || !scheduleId} onClick={() => run(async () => { const value = await request(`/api/schedules/${scheduleId}/runs`); setHistory(value); return value; })}>{t.history}</button>{history && <pre>{JSON.stringify(history, null, 2)}</pre>}</details>
    <h3>{t.status}</h3><pre aria-live="polite">{status}</pre>
  </section>;
}
