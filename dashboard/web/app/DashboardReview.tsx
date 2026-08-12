"use client";

import * as echarts from "echarts";
import { useEffect, useMemo, useRef, useState } from "react";

type Language = "en" | "pt";
type ChartKind = "bar" | "line" | "pie";
type Decision = "pending" | "approved" | "revision";

type Props = { language: Language; context: Record<string, string> };

const labels = {
  en: { title: "Synthetic dashboard review", notice: "All values are invented. Approvals apply to every selected output.", total: "Total value", average: "Average value", records: "Records", category: "Category", value: "Value", approve: "Approve section", revise: "Request revision", revision: "Describe the change", apply: "Apply revision", color: "Accent color", chart: "Chart type", up: "Move up", down: "Move down", approved: "Approved", pending: "Pending review", changed: "Revision requested" },
  pt: { title: "Revisão sintética do dashboard", notice: "Todos os valores são inventados. As aprovações valem para todas as saídas selecionadas.", total: "Valor total", average: "Valor médio", records: "Registros", category: "Categoria", value: "Valor", approve: "Aprovar seção", revise: "Solicitar revisão", revision: "Descreva a alteração", apply: "Aplicar revisão", color: "Cor de destaque", chart: "Tipo de gráfico", up: "Mover para cima", down: "Mover para baixo", approved: "Aprovado", pending: "Aguardando revisão", changed: "Revisão solicitada" },
};

const rows = Array.from({ length: 18 }, (_, index) => ({
  category: `Group ${String.fromCharCode(65 + (index % 5))}`,
  value: 240 + ((index * 173) % 920),
}));

function Chart({ color, kind }: { color: string; kind: ChartKind }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    const grouped = Object.entries(rows.reduce<Record<string, number>>((result, row) => {
      result[row.category] = (result[row.category] ?? 0) + row.value;
      return result;
    }, {}));
    chart.setOption(kind === "pie" ? {
      color: [color, "#8da399", "#cfab72", "#687b91", "#a98285"],
      tooltip: { trigger: "item" },
      series: [{ type: "pie", radius: ["48%", "72%"], data: grouped.map(([name, value]) => ({ name, value })) }],
    } : {
      color: [color], tooltip: { trigger: "axis" }, grid: { left: 45, right: 16, top: 18, bottom: 34 },
      xAxis: { type: "category", data: grouped.map(([name]) => name) }, yAxis: { type: "value" },
      series: [{ type: kind, data: grouped.map(([, value]) => value), smooth: kind === "line" }],
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.dispose(); };
  }, [color, kind]);
  return <div ref={ref} className="chart-canvas" role="img" aria-label="Synthetic grouped values" />;
}

export default function DashboardReview({ language, context }: Props) {
  const t = labels[language];
  const [color, setColor] = useState("#23543c");
  const [kind, setKind] = useState<ChartKind>("bar");
  const [order, setOrder] = useState(["summary", "chart", "details"]);
  const [decisions, setDecisions] = useState<Record<string, Decision>>({ summary: "pending", chart: "pending", details: "pending" });
  const [feedback, setFeedback] = useState("");
  const [runtimeStatus, setRuntimeStatus] = useState("checking");
  const total = useMemo(() => rows.reduce((sum, row) => sum + row.value, 0), []);
  useEffect(() => {
    const saved = window.localStorage.getItem("dashboard-review-controls");
    if (saved) {
      try {
        const value = JSON.parse(saved) as { color?: string; kind?: ChartKind; order?: string[]; decisions?: Record<string, Decision> };
        if (value.color) setColor(value.color);
        if (value.kind) setKind(value.kind);
        if (value.order) setOrder(value.order);
        if (value.decisions) setDecisions(value.decisions);
      } catch { /* stale local controls are ignored */ }
    }
    fetch("/backend/api/hermes/status")
      .then((response) => setRuntimeStatus(response.ok ? "connected" : "unavailable"))
      .catch(() => setRuntimeStatus("unavailable"));
  }, []);
  useEffect(() => {
    window.localStorage.setItem("dashboard-review-controls", JSON.stringify({ color, kind, order, decisions }));
  }, [color, kind, order, decisions]);
  const move = (id: string, offset: number) => setOrder((current) => {
    const source = current.indexOf(id); const target = source + offset;
    if (target < 0 || target >= current.length) return current;
    const next = [...current]; [next[source], next[target]] = [next[target], next[source]]; return next;
  });
  const status = (id: string) => decisions[id] === "approved" ? t.approved : decisions[id] === "revision" ? t.changed : t.pending;
  const controls = (id: string) => <div className="section-actions"><span className={`status ${decisions[id]}`}>{status(id)}</span><button onClick={() => setDecisions({ ...decisions, [id]: "approved" })}>{t.approve}</button><button onClick={() => setDecisions({ ...decisions, [id]: "revision" })}>{t.revise}</button><button aria-label={t.up} onClick={() => move(id, -1)}>↑</button><button aria-label={t.down} onClick={() => move(id, 1)}>↓</button></div>;

  const sections: Record<string, React.ReactNode> = {
    summary: <section className="review-section" key="summary"><header><div><p className="section-label">01</p><h2>{language === "pt" ? "Resumo" : "Summary"}</h2></div>{controls("summary")}</header><div className="kpi-grid"><article><span>{t.total}</span><strong>{total.toLocaleString()}</strong></article><article><span>{t.average}</span><strong>{Math.round(total / rows.length).toLocaleString()}</strong></article><article><span>{t.records}</span><strong>{rows.length}</strong></article></div></section>,
    chart: <section className="review-section" key="chart"><header><div><p className="section-label">02</p><h2>{language === "pt" ? "Distribuição" : "Distribution"}</h2></div>{controls("chart")}</header><Chart color={color} kind={kind} /></section>,
    details: <section className="review-section" key="details"><header><div><p className="section-label">03</p><h2>{language === "pt" ? "Detalhes" : "Details"}</h2></div>{controls("details")}</header><div className="table-wrap"><table><thead><tr><th>{t.category}</th><th>{t.value}</th></tr></thead><tbody>{rows.slice(0, 8).map((row, index) => <tr key={index}><td>{row.category}</td><td>{row.value.toLocaleString()}</td></tr>)}</tbody></table></div></section>,
  };

  return <main className="review-shell" style={{ "--accent": color } as React.CSSProperties}>
    <aside className="review-sidebar"><p className="eyebrow">Dashboard Agent</p><h1>{t.title}</h1><p>{t.notice}</p><p className="runtime-status">Runtime: {runtimeStatus}</p><dl>{Object.entries(context).slice(0, 3).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{value}</dd></div>)}</dl><label>{t.color}<input type="color" value={color} onChange={(event) => setColor(event.target.value)} /></label><label>{t.chart}<select value={kind} onChange={(event) => setKind(event.target.value as ChartKind)}><option value="bar">Bar</option><option value="line">Line</option><option value="pie">Donut</option></select></label><label>{t.revision}<textarea rows={4} value={feedback} onChange={(event) => setFeedback(event.target.value)} /></label><button className="primary" disabled={!feedback.trim()} onClick={() => { setFeedback(""); setDecisions((current) => Object.fromEntries(Object.keys(current).map((key) => [key, current[key] === "revision" ? "pending" : current[key]])) as Record<string, Decision>); }}>{t.apply}</button></aside>
    <div className="dashboard-preview"><div className="synthetic-banner">{t.notice}</div>{order.map((id) => sections[id])}</div>
  </main>;
}
