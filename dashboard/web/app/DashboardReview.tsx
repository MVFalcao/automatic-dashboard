"use client";

import * as echarts from "echarts";
import { useEffect, useMemo, useRef, useState } from "react";
import ProjectOperations from "./ProjectOperations";

type Language = "en" | "pt";
type ChartKind = "bar" | "line" | "pie";
type Field = { id: string; label: string; kind: string };
type Metric = { id: string; label: string; explanation: string };
type Section = { id: string; title: string; kind: string; metric_ids: string[]; field_ids: string[]; depends_on: string[]; order: number };
type Document = {
  specification: { title: string; fields: Field[]; metrics: Metric[]; sections: Section[]; localization: { locale: string }; outputs: { enabled: string[] } };
  records: Array<Record<string, unknown>>;
  metrics: Record<string, number | null>;
  synthetic: boolean;
};
type Approval = { approval_id: string; sections: Record<string, { section_id: string; status: "pending" | "approved" | "rejected" | "blocked"; depends_on: string[] }>; ready_to_activate: boolean };
type Workspace = { document: Document; approval: Approval; project_id: string | null };
type Draft = { version: number; accent_color: string; chart_type: ChartKind; section_order: string[]; terminology: Record<string, string>; feedback_applied_by_hermes: boolean };
type Props = { language: Language; sessionId: string; context: Record<string, string> };

const labels = {
  en: { title: "Synthetic dashboard review", notice: "All values are invented. The server generated this document; approvals apply to every selected output.", approve: "Approve section", revise: "Request revision", feedback: "Describe the change", feedbackSafe: "This feedback is non-confidential and may be sent to Hermes", apply: "Ask Hermes", save: "Save controls as draft", activate: "Create project and activate approved specification", saved: "Project saved and ready for source setup.", color: "Accent color", chart: "Chart type", approved: "Approved", pending: "Pending review", rejected: "Revision requested", blocked: "Blocked by dependency", runtime: "Hermes runtime", loading: "Loading the server-generated preview…", retry: "Try again", draft: "Draft", noMutation: "The active approved specification is unchanged.", error: "The preview could not be loaded.", guidance: "Check that the local API and Hermes runtime are running, then retry." },
  pt: { title: "Revisão sintética do dashboard", notice: "Todos os valores são inventados. O servidor gerou este documento; as aprovações valem para todas as saídas.", approve: "Aprovar seção", revise: "Solicitar revisão", feedback: "Descreva a alteração", feedbackSafe: "Este feedback não é confidencial e pode ser enviado ao Hermes", apply: "Pedir ao Hermes", save: "Salvar controles como rascunho", activate: "Criar projeto e ativar especificação aprovada", saved: "Projeto salvo e pronto para configurar a fonte.", color: "Cor de destaque", chart: "Tipo de gráfico", approved: "Aprovado", pending: "Aguardando revisão", rejected: "Revisão solicitada", blocked: "Bloqueado por dependência", runtime: "Runtime Hermes", loading: "Carregando a prévia gerada pelo servidor…", retry: "Tentar novamente", draft: "Rascunho", noMutation: "A especificação ativa aprovada não foi alterada.", error: "Não foi possível carregar a prévia.", guidance: "Verifique se a API local e o Hermes estão ativos e tente novamente." },
};

function Chart({ document, color, kind, section }: { document: Document; color: string; kind: ChartKind; section: Section }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    const fields = section.field_ids.length ? section.field_ids : document.specification.fields.map((item) => item.id);
    const dimension = fields.find((id) => document.specification.fields.find((item) => item.id === id)?.kind === "text") ?? document.specification.fields[0]?.id;
    const numeric = fields.find((id) => document.specification.fields.find((item) => item.id === id)?.kind === "number") ?? document.specification.fields.find((item) => item.kind === "number")?.id;
    const grouped = Object.entries(document.records.reduce<Record<string, number>>((result, row) => {
      const key = String(row[dimension] ?? "—");
      result[key] = (result[key] ?? 0) + Number(numeric ? row[numeric] ?? 0 : 0);
      return result;
    }, {}));
    chart.setOption(kind === "pie" ? {
      color: [color, "#8da399", "#cfab72", "#687b91", "#a98285"], tooltip: { trigger: "item" },
      series: [{ type: "pie", radius: ["48%", "72%"], data: grouped.map(([name, value]) => ({ name, value })) }],
    } : {
      color: [color], tooltip: { trigger: "axis" }, grid: { left: 45, right: 16, top: 18, bottom: 34 },
      xAxis: { type: "category", data: grouped.map(([name]) => name) }, yAxis: { type: "value" },
      series: [{ type: kind, data: grouped.map(([, value]) => value), smooth: kind === "line" }],
    });
    const resize = () => chart.resize(); window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.dispose(); };
  }, [color, document, kind, section]);
  return <div ref={ref} className="chart-canvas" role="img" aria-label={section.title} />;
}

export default function DashboardReview({ language, sessionId, context }: Props) {
  const t = labels[language];
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [color, setColor] = useState("#23543c");
  const [kind, setKind] = useState<ChartKind>("bar");
  const [order, setOrder] = useState<string[]>([]);
  const [feedback, setFeedback] = useState("");
  const [feedbackSafe, setFeedbackSafe] = useState(false);
  const [runtime, setRuntime] = useState<Record<string, unknown>>({ ready: false });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [projectId, setProjectId] = useState<string | null>(null);
  const locale = language === "pt" ? "pt-BR" : "en-US";

  const load = async () => {
    setError("");
    try {
      const [previewResponse, draftResponse, runtimeResponse] = await Promise.all([
        fetch(`/backend/api/intake/${sessionId}/preview`, { cache: "no-store" }),
        fetch(`/backend/api/intake/${sessionId}/draft`, { cache: "no-store" }),
        fetch("/backend/api/hermes/status", { cache: "no-store" }),
      ]);
      if (!previewResponse.ok) throw new Error("preview");
      const preview = await previewResponse.json() as Workspace;
      setWorkspace(preview);
      setProjectId(preview.project_id);
      const saved = draftResponse.ok ? await draftResponse.json() as Draft | null : null;
      setDraft(saved);
      setColor(saved?.accent_color ?? "#23543c"); setKind(saved?.chart_type ?? "bar");
      setOrder(saved?.section_order ?? [...preview.document.specification.sections].sort((a, b) => a.order - b.order).map((item) => item.id));
      setRuntime(runtimeResponse.ok ? await runtimeResponse.json() : { ready: false });
    } catch { setError(`${t.error} ${t.guidance}`); }
  };
  useEffect(() => { void load(); }, [sessionId]);

  const decide = async (sectionId: string, approve: boolean) => {
    if (!workspace) return;
    setBusy(true); setError("");
    try {
      const response = await fetch(`/backend/api/approvals/${workspace.approval.approval_id}/sections/${sectionId}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approve, feedback: approve ? null : feedback || "Revision requested in the review workspace" }),
      });
      if (!response.ok) throw new Error("decision");
      setWorkspace({ ...workspace, approval: await response.json() as Approval });
    } catch { setError(t.guidance); } finally { setBusy(false); }
  };
  const saveDraft = async (naturalLanguage: boolean) => {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/backend/api/intake/${sessionId}/draft`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ accent_color: color, chart_type: kind, section_order: order, terminology: draft?.terminology ?? {}, feedback: naturalLanguage ? feedback : null, feedback_non_confidential: naturalLanguage && feedbackSafe }),
      });
      if (!response.ok) { const problem = await response.json(); throw new Error(problem.detail ?? t.guidance); }
      const next = await response.json() as Draft; setDraft(next); setFeedback(""); setFeedbackSafe(false);
      setColor(next.accent_color); setKind(next.chart_type); setOrder(next.section_order);
      await load();
    } catch (problem) { setError(problem instanceof Error ? problem.message : t.guidance); } finally { setBusy(false); }
  };
  const activate = async () => {
    const directory = context.project_location;
    if (!workspace || !directory) { setError(t.guidance); return; }
    setBusy(true); setError("");
    try {
      const identifier = crypto.randomUUID();
      const created = await fetch("/backend/api/projects", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          schema_version: 2, id: identifier, name: workspace.document.specification.title.slice(0, 120), language,
          outputs: workspace.document.specification.outputs.enabled, project_directory: directory,
          non_confidential_confirmed: true,
        }),
      });
      if (!created.ok) { const problem = await created.json(); throw new Error(problem.detail ?? t.guidance); }
      const approved = await fetch(`/backend/api/projects/${identifier}/specifications`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ specification: workspace.document.specification, approval_id: workspace.approval.approval_id, approved_by: "local-user", confirmed_non_confidential: true }),
      });
      if (!approved.ok) { const problem = await approved.json(); throw new Error(problem.detail ?? t.guidance); }
      const linked = await fetch(`/backend/api/intake/${sessionId}/project-link`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: identifier }),
      });
      if (!linked.ok) { const problem = await linked.json(); throw new Error(problem.detail ?? t.guidance); }
      setProjectId(identifier);
    } catch (problem) { setError(problem instanceof Error ? problem.message : t.guidance); } finally { setBusy(false); }
  };
  const move = (id: string, offset: number) => setOrder((current) => {
    const source = current.indexOf(id); const target = source + offset; if (target < 0 || target >= current.length) return current;
    const next = [...current]; [next[source], next[target]] = [next[target], next[source]]; return next;
  });
  const sectionsById = useMemo(() => Object.fromEntries((workspace?.document.specification.sections ?? []).map((item) => [item.id, item])), [workspace]);

  if (!workspace) return <main className="shell"><section className="panel"><h1>{t.title}</h1><p>{error || t.loading}</p>{error && <button onClick={() => void load()}>{t.retry}</button>}</section></main>;
  const { document, approval } = workspace;
  const statusLabel = (status: string) => ({ approved: t.approved, rejected: t.rejected, blocked: t.blocked, pending: t.pending }[status] ?? status);
  const display = (value: unknown) => typeof value === "number" ? value.toLocaleString(locale) : String(value ?? "");

  return <main className="review-shell" style={{ "--accent": color } as React.CSSProperties}>
    <aside className="review-sidebar">
      <p className="eyebrow">Dashboard Agent</p><h1>{t.title}</h1><p>{t.notice}</p>
      <p className={`runtime-status ${runtime.ready ? "approved" : "revision"}`}>{t.runtime}: {runtime.ready ? "ready" : "unavailable"}</p>
      {draft && <p>{t.draft} v{draft.version}. {t.noMutation}</p>}
      <dl>{Object.entries(context).slice(0, 3).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{value}</dd></div>)}</dl>
      <label>{t.color}<input type="color" value={color} onChange={(event) => setColor(event.target.value)} /></label>
      <label>{t.chart}<select value={kind} onChange={(event) => setKind(event.target.value as ChartKind)}><option value="bar">Bar</option><option value="line">Line</option><option value="pie">Donut</option></select></label>
      <button onClick={() => void saveDraft(false)} disabled={busy}>{t.save}</button>
      <label>{t.feedback}<textarea rows={4} value={feedback} onChange={(event) => setFeedback(event.target.value)} /></label>
      <label><input type="checkbox" checked={feedbackSafe} onChange={(event) => setFeedbackSafe(event.target.checked)} /> {t.feedbackSafe}</label>
      <button className="primary" disabled={busy || !feedback.trim() || !feedbackSafe || !runtime.ready} onClick={() => void saveDraft(true)}>{t.apply}</button>
      {approval.ready_to_activate && !projectId && <button className="primary" disabled={busy || !context.project_location} onClick={() => void activate()}>{t.activate}</button>}
      {projectId && <p className="success">{t.saved}</p>}
      {error && <p className="error" role="alert">{error}</p>}
    </aside>
    <div className="dashboard-preview"><div className="synthetic-banner">{t.notice}</div>{order.map((id, position) => {
      const section = sectionsById[id]; if (!section) return null;
      const decision = approval.sections[id];
      const controls = <div className="section-actions"><span className={`status ${decision?.status ?? "pending"}`}>{statusLabel(decision?.status ?? "pending")}</span><button disabled={busy || decision?.status === "blocked"} onClick={() => void decide(id, true)}>{t.approve}</button><button disabled={busy || decision?.status === "blocked"} onClick={() => void decide(id, false)}>{t.revise}</button><button aria-label="up" onClick={() => move(id, -1)}>↑</button><button aria-label="down" onClick={() => move(id, 1)}>↓</button></div>;
      const metrics = document.specification.metrics.filter((metric) => section.metric_ids.includes(metric.id));
      const fields = document.specification.fields.filter((field) => section.field_ids.includes(field.id));
      return <section className="review-section" key={id}><header><div><p className="section-label">{String(position + 1).padStart(2, "0")}</p><h2>{section.title}</h2></div>{controls}</header>
        {section.kind === "metrics" && <div className="kpi-grid">{metrics.map((metric) => <article key={metric.id}><span>{metric.label}</span><strong>{display(document.metrics[metric.id])}</strong><small>{metric.explanation}</small></article>)}</div>}
        {section.kind === "chart" && <Chart document={document} color={color} kind={kind} section={section} />}
        {section.kind === "table" && <div className="table-wrap"><table><thead><tr>{fields.map((field) => <th key={field.id}>{field.label}</th>)}</tr></thead><tbody>{document.records.slice(0, 8).map((row, index) => <tr key={index}>{fields.map((field) => <td key={field.id}>{display(row[field.id])}</td>)}</tr>)}</tbody></table></div>}
      </section>;
    })}{projectId && <ProjectOperations language={language} projectId={projectId} projectDirectory={context.project_location} outputs={document.specification.outputs.enabled} fields={document.specification.fields} />}</div>
  </main>;
}
