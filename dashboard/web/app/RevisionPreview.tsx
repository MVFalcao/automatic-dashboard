"use client";

import type { CSSProperties } from "react";
import { PreviewSectionBody, type PreviewField, type PreviewMetric, type PreviewSectionSpec } from "./DashboardPreviewSection";

export type RevisionApproval = { approval_id: string; ready_to_activate: boolean; sections: Record<string, { section_id: string; status: "pending" | "approved" | "rejected" | "blocked" }> };
export type RevisionSpecification = { title: string; fields: PreviewField[]; metrics: PreviewMetric[]; outputs: { enabled: string[] }; sections: PreviewSectionSpec[]; style: { palette: string[] } };
export type Revision = { id: string; base_version: number; mode: "update" | "recreate"; hermes_response: string; active_specification_unchanged: boolean; specification: RevisionSpecification; approval: RevisionApproval; preview: { synthetic: boolean; metrics: Record<string, number | null>; records: Array<Record<string, unknown>> } };

type Copy = {
  hermesResponse: string;
  syntheticRevision: string;
  activeUnchanged: string;
  returnProject: string;
  approveSection: string;
  rejectSection: string;
  activationSafe: string;
  activateRevision: string;
};

type Props = {
  revision: Revision;
  busy: boolean;
  language: "en" | "pt";
  projectNonConfidential: boolean;
  revisionActivationSafe: boolean;
  onActivationSafeChange: (value: boolean) => void;
  onDecide: (sectionId: string, approve: boolean) => void;
  onActivate: () => void;
  onReturn: () => void;
  copy: Copy;
};

export default function RevisionPreview({
  revision, busy, language, projectNonConfidential, revisionActivationSafe,
  onActivationSafeChange, onDecide, onActivate, onReturn, copy: t,
}: Props) {
  const accent = revision.specification.style.palette[0] ?? "#1D4ED8";
  const locale = language === "pt" ? "pt-BR" : "en-US";
  return (
    <div className="revision-preview" style={{ "--accent": accent } as CSSProperties}>
      <section className="hermes-response" aria-live="polite">
        <strong>{t.hermesResponse}</strong>
        <p>{revision.hermes_response}</p>
      </section>
      <div className="revision-preview-heading">
        <div>
          <span className="status revision">{t.syntheticRevision}</span>
          <h3>{revision.specification.title}</h3>
          <p>{t.activeUnchanged} · v{revision.base_version}</p>
        </div>
        <button onClick={onReturn}>{t.returnProject}</button>
      </div>
      {revision.specification.sections.map((section) => {
        const decision = revision.approval.sections[section.id];
        return (
          <section className="review-section revision-section" key={section.id}>
            <header>
              <h3>{section.title}</h3>
              <div className="section-actions">
                <span className={`status ${decision?.status === "approved" ? "approved" : "revision"}`}>{decision?.status ?? "pending"}</span>
                <button disabled={busy || decision?.status === "blocked"} onClick={() => onDecide(section.id, true)}>{t.approveSection}</button>
                <button disabled={busy || decision?.status === "blocked"} onClick={() => onDecide(section.id, false)}>{t.rejectSection}</button>
              </div>
            </header>
            <PreviewSectionBody
              section={section}
              fields={revision.specification.fields}
              metrics={revision.specification.metrics}
              records={revision.preview.records}
              metricValues={revision.preview.metrics}
              color={accent}
              chartKind="bar"
              locale={locale}
            />
          </section>
        );
      })}
      {revision.approval.ready_to_activate && (
        <div className="revision-activation">
          {!projectNonConfidential && (
            <label>
              <input type="checkbox" checked={revisionActivationSafe} onChange={(event) => onActivationSafeChange(event.target.checked)} /> {t.activationSafe}
            </label>
          )}
          <button className="primary" disabled={busy || (!projectNonConfidential && !revisionActivationSafe)} onClick={onActivate}>{t.activateRevision}</button>
        </div>
      )}
    </div>
  );
}
