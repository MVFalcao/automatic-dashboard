"use client";

import { useEffect, useState } from "react";

type Language = "en" | "pt";
type HermesStatus = { ready: boolean; provider_ready: boolean; codex_compatible: boolean; codex_model: string | null; remediation: string | null };
type Diagnostics = { ok: boolean; components: Record<string, { ok: boolean; remediation: string | null }> };

const copy = {
  en: {
    notReady: "The local agent runtime is not ready.",
    codexIncompatible: (model: string | null) => `Codex is connected but using "${model ?? "an unrecognized model"}" instead of gpt-5.5. Reconnect Codex to fix this.`,
    diagnosticIssue: (name: string, remediation: string | null) => `${name}: ${remediation ?? "needs attention"}`,
  },
  pt: {
    notReady: "O runtime local do agente não está pronto.",
    codexIncompatible: (model: string | null) => `O Codex está conectado, mas usando "${model ?? "um modelo não reconhecido"}" em vez de gpt-5.5. Reconecte o Codex para corrigir isso.`,
    diagnosticIssue: (name: string, remediation: string | null) => `${name}: ${remediation ?? "requer atenção"}`,
  },
};

/** Surfaces provider/runtime problems proactively instead of leaving them silent until something fails. */
export default function StatusBanner({ language }: { language: Language }) {
  const t = copy[language];
  const [issues, setIssues] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const collected: string[] = [];
      try {
        const response = await fetch("/backend/api/hermes/status", { cache: "no-store" });
        if (response.ok) {
          const status = await response.json() as HermesStatus;
          if (!status.ready || !status.provider_ready) collected.push(t.notReady);
          if (status.codex_compatible === false) collected.push(t.codexIncompatible(status.codex_model));
        }
      } catch { /* treated as no news; the rest of the UI already surfaces connection failures */ }
      try {
        const response = await fetch("/backend/api/diagnostics", { cache: "no-store" });
        if (response.ok) {
          const diagnostics = await response.json() as Diagnostics;
          if (!diagnostics.ok) {
            for (const [name, component] of Object.entries(diagnostics.components)) {
              if (!component.ok) collected.push(t.diagnosticIssue(name, component.remediation));
            }
          }
        }
      } catch { /* diagnostics are best-effort here */ }
      if (!cancelled) setIssues(collected);
    };
    void load();
    return () => { cancelled = true; };
  }, [language]);

  if (!issues.length) return null;
  return <div className="status-banner" role="alert">{issues.map((issue) => <p key={issue}>{issue}</p>)}</div>;
}
