"use client";

import * as echarts from "echarts";
import { useEffect, useRef } from "react";

export type ChartKind = "bar" | "line" | "pie";
export type PreviewField = { id: string; label: string; kind: string };
export type PreviewMetric = { id: string; label: string; explanation: string };
export type PreviewSectionSpec = { id: string; title: string; kind: string; metric_ids: string[]; field_ids: string[] };

function display(value: unknown, locale: string): string {
  return typeof value === "number" ? value.toLocaleString(locale) : String(value ?? "");
}

export function Chart({ fields, records, color, kind, section }: {
  fields: PreviewField[];
  records: Array<Record<string, unknown>>;
  color: string;
  kind: ChartKind;
  section: PreviewSectionSpec;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    const sectionFields = section.field_ids.length ? section.field_ids : fields.map((item) => item.id);
    const dimension = sectionFields.find((id) => fields.find((item) => item.id === id)?.kind === "text") ?? sectionFields[0];
    const numeric = sectionFields.find((id) => fields.find((item) => item.id === id)?.kind === "number") ?? fields.find((item) => item.kind === "number")?.id;
    const grouped = Object.entries(records.reduce<Record<string, number>>((result, row) => {
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
  }, [color, fields, records, kind, section]);
  return <div ref={ref} className="chart-canvas" role="img" aria-label={section.title} />;
}

/** Renders a section's body (KPI cards / chart / table) — callers own the header and controls. */
export function PreviewSectionBody({ section, fields, metrics, records, metricValues, color, chartKind, locale }: {
  section: PreviewSectionSpec;
  fields: PreviewField[];
  metrics: PreviewMetric[];
  records: Array<Record<string, unknown>>;
  metricValues: Record<string, number | null>;
  color: string;
  chartKind: ChartKind;
  locale: string;
}) {
  const sectionMetrics = metrics.filter((metric) => section.metric_ids.includes(metric.id));
  const sectionFields = fields.filter((field) => section.field_ids.includes(field.id));
  if (section.kind === "metrics") {
    return <div className="kpi-grid">{sectionMetrics.map((metric) => <article key={metric.id}><span>{metric.label}</span><strong>{display(metricValues[metric.id], locale)}</strong><small>{metric.explanation}</small></article>)}</div>;
  }
  if (section.kind === "chart") {
    return <Chart fields={fields} records={records} color={color} kind={chartKind} section={section} />;
  }
  if (section.kind === "table") {
    return <div className="table-wrap"><table><thead><tr>{sectionFields.map((field) => <th key={field.id}>{field.label}</th>)}</tr></thead><tbody>{records.slice(0, 8).map((row, index) => <tr key={index}>{sectionFields.map((field) => <td key={field.id}>{display(row[field.id], locale)}</td>)}</tr>)}</tbody></table></div>;
  }
  return null;
}
