"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import DashboardReview from "./DashboardReview";

type Language = "en" | "pt";
type IntakeStep = "goal" | "audience" | "reference_sample" | "outputs" | "project_location" | "confirmation" | "complete";

type IntakeResponse = {
  session_id: string;
  language: Language;
  step: IntakeStep;
  question: string | null;
  confirmed_context: Record<string, string>;
};

type ReferenceInspection = {
  filename: string;
  format: string;
  size_bytes: number;
  temporary_copy_deleted: boolean;
  manifest: {
    sections: Array<{ name: string; formula_cells: number; chart_count: number }>;
    assumptions: string[];
    warnings: string[];
  };
  draft_schema: {
    fields: Array<{ id: string; display_name: string; inferred_type: string; confidence: string }>;
    sections: Array<{ id: string; display_name: string; presentation: string; confidence: string }>;
    assumptions: string[];
    requires_user_approval: boolean;
  };
};

type ProjectEntry = { id: string; name: string; project_directory: string };

const contextLabels: Record<Language, Record<string, string>> = {
  en: { goal: "Goal", audience: "Audience", reference_sample: "Reference sample", outputs: "Outputs", project_location: "Project location" },
  pt: { goal: "Objetivo", audience: "Público", reference_sample: "Amostra de referência", outputs: "Saídas", project_location: "Local do projeto" },
};

const copy = {
  en: {
    eyebrow: "Local dashboard workspace",
    intro: "The agent asks one question at a time and does not assume missing requirements.",
    placeholder: "Write your answer here…",
    formats: "Reference samples: Excel, PDF, PNG, JPEG, or SVG",
    privacy: "Your project stays on this computer. Confidential data is never saved without your explicit approval.",
    continue: "Continue",
    finish: "Finish setup",
    complete: "Your initial dashboard requirements are ready for review.",
    understanding: "What I understood",
    confirmationNote: "Review the agent's note before confirming these requirements.",
    upload: "Optional reference sample",
    confidential: "This file contains confidential data",
    extraction: "Allow the agent to inspect data contained in this file",
    inspected: "The temporary upload was inspected and deleted.",
    discovery: "Discovered proposal",
    fields: "Proposed fields",
    sections: "Proposed sections",
    approval: "Every proposal requires your approval before it can be used.",
    error: "The request could not be completed. Please try again.",
    nonConfidential: "This answer is non-confidential and may be saved for restart",
  },
  pt: {
    eyebrow: "Área de trabalho local",
    intro: "O agente faz uma pergunta por vez e não presume requisitos ausentes.",
    placeholder: "Escreva sua resposta aqui…",
    formats: "Amostras aceitas: Excel, PDF, PNG, JPEG ou SVG",
    privacy: "Seu projeto permanece neste computador. Dados confidenciais nunca são salvos sem sua aprovação explícita.",
    continue: "Continuar",
    finish: "Concluir configuração",
    complete: "Os requisitos iniciais do seu dashboard estão prontos para revisão.",
    understanding: "O que o agente entendeu",
    confirmationNote: "Revise a anotação do agente antes de confirmar estes requisitos.",
    upload: "Amostra de referência opcional",
    confidential: "Este arquivo contém dados confidenciais",
    extraction: "Permitir que o agente inspecione os dados contidos neste arquivo",
    inspected: "O arquivo temporário foi inspecionado e excluído.",
    discovery: "Proposta identificada",
    fields: "Campos propostos",
    sections: "Seções propostas",
    approval: "Toda proposta exige sua aprovação antes de ser utilizada.",
    error: "Não foi possível concluir a solicitação. Tente novamente.",
    nonConfidential: "Esta resposta não é confidencial e pode ser salva para reinício",
  },
};

export default function SetupPage() {
  const [language, setLanguage] = useState<Language>("en");
  const [session, setSession] = useState<IntakeResponse | null>(null);
  const [answer, setAnswer] = useState("");
  const [answerNonConfidential, setAnswerNonConfidential] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [confidential, setConfidential] = useState(false);
  const [permitExtraction, setPermitExtraction] = useState(false);
  const [uploadInspected, setUploadInspected] = useState(false);
  const [inspection, setInspection] = useState<ReferenceInspection | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [projects, setProjects] = useState<ProjectEntry[]>([]);
  const text = useMemo(() => copy[language], [language]);

  useEffect(() => {
    if (navigator.language.toLowerCase().startsWith("pt")) setLanguage("pt");
    fetch("/backend/api/projects", { cache: "no-store" }).then((response) => response.ok ? response.json() : []).then(setProjects).catch(() => setProjects([]));
    const identifier = new URLSearchParams(window.location.search).get("intake");
    if (identifier) fetch(`/backend/api/intake/${identifier}`, { cache: "no-store" }).then(async (response) => {
      if (!response.ok) throw new Error(); const restored = await response.json() as IntakeResponse; setSession(restored); setLanguage(restored.language);
    }).catch(() => setError(copy[language].error));
  }, []);

  const start = async (): Promise<IntakeResponse> => {
    const response = await fetch("/backend/api/intake", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language }),
    });
    if (!response.ok) throw new Error("Unable to start intake");
    const created = await response.json() as IntakeResponse;
    window.history.replaceState(null, "", `?intake=${created.session_id}`);
    return created;
  };

  const inspectFile = async () => {
    if (!file) return;
    const payload = new FormData();
    payload.append("file", file);
    payload.append("confidential", String(confidential));
    payload.append("permit_data_extraction", String(permitExtraction));
    const response = await fetch("/backend/api/references/inspect", { method: "POST", body: payload });
    if (!response.ok) throw new Error("Unable to inspect upload");
    setInspection(await response.json());
    setUploadInspected(true);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!answer.trim()) return;
    setBusy(true);
    setError("");
    try {
      const active = session ?? (await start());
      if (active.step === "reference_sample" && file && !uploadInspected) await inspectFile();
      const response = await fetch(`/backend/api/intake/${active.session_id}/answers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ step: active.step, answer: answer.trim(), persist_non_confidential: answerNonConfidential }),
      });
      if (!response.ok) throw new Error("Unable to save answer");
      const next: IntakeResponse = await response.json();
      setSession(next);
      setLanguage(next.language);
      setAnswer("");
      setAnswerNonConfidential(false);
      setFile(null);
      setConfidential(false);
      setPermitExtraction(false);
      setUploadInspected(false);
      setInspection(null);
    } catch {
      setError(text.error);
    } finally {
      setBusy(false);
    }
  };

  const question = session?.question ?? (language === "pt"
    ? "O que este dashboard deve ajudar você a entender ou decidir?"
    : "What should this dashboard help you understand or decide?");
  const isReferenceStep = session?.step === "reference_sample";
  const isConfirmationStep = session?.step === "confirmation";

  if (session?.step === "complete") {
    return <DashboardReview language={language} sessionId={session.session_id} context={session.confirmed_context} />;
  }

  return (
    <main className="shell">
      <section className="panel" aria-labelledby="setup-title">
        {!session && (
          <div className="language-switch" aria-label="Language">
            <button className={language === "en" ? "active" : ""} onClick={() => setLanguage("en")}>EN</button>
            <button className={language === "pt" ? "active" : ""} onClick={() => setLanguage("pt")}>PT</button>
          </div>
        )}
        <p className="eyebrow">{text.eyebrow}</p>
        {!session && projects.length > 0 && <nav aria-label="Projects"><p>{language === "pt" ? "Projetos salvos" : "Saved projects"}</p><ul>{projects.map((project) => <li key={project.id}>{project.name} · <code>{project.project_directory}</code></li>)}</ul></nav>}
        {
          <form onSubmit={submit}>
            <h1 id="setup-title">{question}</h1>
            {(!session || session.step === "goal") && <p className="intro">{text.intro}</p>}
            {isConfirmationStep && session && (
              <section className="understanding-note" aria-labelledby="understanding-title">
                <h2 id="understanding-title">{text.understanding}</h2>
                <p>{text.confirmationNote}</p>
                <dl>
                  {Object.entries(session.confirmed_context).map(([key, value]) => (
                    <div key={key}><dt>{contextLabels[language][key] ?? key}</dt><dd>{value}</dd></div>
                  ))}
                </dl>
              </section>
            )}
            <label htmlFor="answer" className="sr-only">{question}</label>
            <textarea id="answer" value={answer} onChange={(event) => setAnswer(event.target.value)} placeholder={text.placeholder} rows={5} />
            <label><input type="checkbox" checked={answerNonConfidential} onChange={(event) => setAnswerNonConfidential(event.target.checked)} /> {text.nonConfidential}</label>
            {isReferenceStep && (
              <fieldset className="upload-box">
                <legend>{text.upload}</legend>
                <input type="file" accept=".xlsx,.pdf,.png,.jpg,.jpeg,.svg" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
                <label><input type="checkbox" checked={confidential} onChange={(event) => setConfidential(event.target.checked)} /> {text.confidential}</label>
                <label><input type="checkbox" checked={permitExtraction} onChange={(event) => setPermitExtraction(event.target.checked)} /> {text.extraction}</label>
                {uploadInspected && <p className="success">{text.inspected}</p>}
                {inspection && (
                  <div className="discovery-review">
                    <h2>{text.discovery}</h2>
                    <p>{text.approval}</p>
                    <h3>{text.sections}</h3>
                    <ul>{inspection.draft_schema.sections.map((section) => <li key={section.id}>{section.display_name} · {section.presentation} · {section.confidence}</li>)}</ul>
                    <h3>{text.fields}</h3>
                    {inspection.draft_schema.fields.length ? (
                      <ul>{inspection.draft_schema.fields.map((field) => <li key={field.id}>{field.display_name} · {field.inferred_type} · {field.confidence}</li>)}</ul>
                    ) : <p>—</p>}
                  </div>
                )}
              </fieldset>
            )}
            <div className="notes"><p>{text.formats}</p><p>{text.privacy}</p></div>
            {error && <p className="error" role="alert">{error}</p>}
            <button className="primary" disabled={busy || !answer.trim()}>{busy ? "…" : session?.step === "confirmation" ? text.finish : text.continue}</button>
          </form>
        }
      </section>
    </main>
  );
}
