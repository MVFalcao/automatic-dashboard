"use client";

import { useState } from "react";

type Language = "en" | "pt";
type CodexOAuthStatus = {
  session_id: string;
  project_id: string | null;
  status: string;
  verification_url: string | null;
  user_code: string | null;
  expires_in: number;
  error: string | null;
  recoverable: boolean;
  remediation: string | null;
  provider: string;
  model: string;
  compatible: boolean;
};

const copy = {
  en: {
    step: "Initial setup",
    title: "Connect your AI agent",
    intro: "Connect an agent before creating or opening dashboard projects. Your provider credentials stay in the protected store on this computer.",
    codexTitle: "Continue with Codex",
    codexDescription: "Sign in through your browser. The application never receives or stores your OAuth token.",
    connectCodex: "Connect Codex in browser",
    retryCodex: "Try Codex login again",
    code: "Verification code",
    cancel: "Cancel login",
    alternative: "Or use a provider API key",
    provider: "Provider",
    apiKey: "API key",
    apiKeyHelp: "The key is sent directly to the operating-system credential vault and is never saved in a project.",
    connectProvider: "Connect provider",
    connecting: "Connecting…",
    connected: "Agent connected. Opening your projects…",
    error: "The agent could not be connected. Review the guidance and try again.",
    privacy: "Required before project setup · Local application · Credentials never enter project files",
  },
  pt: {
    step: "Configuração inicial",
    title: "Conecte seu agente de IA",
    intro: "Conecte um agente antes de criar ou abrir projetos de dashboard. As credenciais do provedor permanecem no armazenamento protegido deste computador.",
    codexTitle: "Continuar com Codex",
    codexDescription: "Faça login pelo navegador. A aplicação nunca recebe nem armazena seu token OAuth.",
    connectCodex: "Conectar Codex pelo navegador",
    retryCodex: "Tentar login do Codex novamente",
    code: "Código de verificação",
    cancel: "Cancelar login",
    alternative: "Ou use uma chave de API de outro provedor",
    provider: "Provedor",
    apiKey: "Chave de API",
    apiKeyHelp: "A chave é enviada diretamente ao cofre de credenciais do sistema e nunca é salva em um projeto.",
    connectProvider: "Conectar provedor",
    connecting: "Conectando…",
    connected: "Agente conectado. Abrindo seus projetos…",
    error: "Não foi possível conectar o agente. Revise a orientação e tente novamente.",
    privacy: "Obrigatório antes do projeto · Aplicação local · Credenciais nunca entram nos arquivos do projeto",
  },
};

function errorDetail(value: unknown, fallback: string): string {
  if (typeof value === "string") return value;
  if (value && typeof value === "object") {
    const detail = value as { message?: string; fields?: Array<{ field?: string; message?: string }> };
    if (detail.fields?.length) return detail.fields.map((item) => item.message ?? fallback).join(" · ");
    if (detail.message) return detail.message;
  }
  return fallback;
}

async function request(path: string, init?: RequestInit) {
  const response = await fetch(`/backend${path}`, { ...init, cache: "no-store" });
  const value = response.status === 204 ? null : await response.json();
  if (!response.ok) throw new Error(errorDetail(value?.detail, `HTTP ${response.status}`));
  return value;
}

export default function AgentProviderSetup({
  language,
  onLanguageChange,
  onConnected,
}: {
  language: Language;
  onLanguageChange: (language: Language) => void;
  onConnected: () => void;
}) {
  const t = copy[language];
  const [provider, setProvider] = useState("gemini");
  const [apiKey, setApiKey] = useState("");
  const [oauth, setOauth] = useState<CodexOAuthStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const connectCodex = async () => {
    setBusy(true);
    setError("");
    setMessage("");
    const popup = window.open("about:blank", "codex-oauth", "width=720,height=760");
    if (popup) popup.opener = null;
    let openedVerification = false;
    try {
      let current = await request("/api/providers/oauth/codex/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      }) as CodexOAuthStatus;
      setOauth(current);
      while (current.status === "pending" && current.expires_in > 0) {
        if (current.verification_url && !openedVerification) {
          if (popup) popup.location.href = current.verification_url;
          else window.open(current.verification_url, "_blank", "noopener,noreferrer");
          openedVerification = true;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
        current = await request(`/api/providers/oauth/codex/${current.session_id}`) as CodexOAuthStatus;
        setOauth(current);
      }
      if (current.status !== "connected") throw new Error(current.error ?? `Codex login ${current.status}`);
      if (popup && !openedVerification) popup.close();
      setMessage(t.connected);
      onConnected();
    } catch (problem) {
      if (popup && !openedVerification) popup.close();
      setError(problem instanceof Error ? problem.message : t.error);
    } finally {
      setBusy(false);
    }
  };

  const cancelCodex = async () => {
    if (!oauth) return;
    setCancelling(true);
    try {
      await request(`/api/providers/oauth/codex/${oauth.session_id}`, { method: "DELETE" });
      setOauth({ ...oauth, status: "cancelled", recoverable: true });
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : t.error);
    } finally {
      setCancelling(false);
    }
  };

  const connectApiKey = async () => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await request("/api/providers/connect-api-key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider,
          account_id: "local",
          model: `${provider}-default`,
          api_key: apiKey,
          capabilities: ["conversation", "structured_output", "insights"],
        }),
      });
      setApiKey("");
      setMessage(t.connected);
      onConnected();
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : t.error);
    } finally {
      setBusy(false);
    }
  };

  return <main className="shell">
    <section className="panel agent-onboarding" aria-labelledby="agent-setup-title">
      <div className="language-switch" aria-label="Language">
        <button className={language === "en" ? "active" : ""} onClick={() => onLanguageChange("en")}>EN</button>
        <button className={language === "pt" ? "active" : ""} onClick={() => onLanguageChange("pt")}>PT</button>
      </div>
      <p className="eyebrow">Dashboard Agent · {t.step}</p>
      <h1 id="agent-setup-title">{t.title}</h1>
      <p className="intro">{t.intro}</p>

      <section className="provider-card provider-card-primary" aria-labelledby="codex-title">
        <div><span className="provider-mark">C</span><div><h2 id="codex-title">{t.codexTitle}</h2><p>{t.codexDescription}</p></div></div>
        <button className="primary" disabled={busy} onClick={() => void connectCodex()}>{busy ? t.connecting : oauth?.recoverable ? t.retryCodex : t.connectCodex}</button>
        {oauth && <div className="oauth-status" aria-live="polite"><strong>{oauth.status}</strong>{oauth.user_code && <span>{t.code}: <code>{oauth.user_code}</code></span>}{oauth.remediation && <span>{oauth.remediation}</span>}{oauth.status === "pending" && <button disabled={cancelling} onClick={() => void cancelCodex()}>{t.cancel}</button>}</div>}
      </section>

      <div className="provider-divider"><span>{t.alternative}</span></div>
      <section className="provider-card" aria-label={t.alternative}>
        <label>{t.provider}<select value={provider} onChange={(event) => setProvider(event.target.value)}><option value="gemini">Gemini</option><option value="claude">Claude</option><option value="deepseek">DeepSeek</option></select></label>
        <label>{t.apiKey}<input type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} /></label>
        <p>{t.apiKeyHelp}</p>
        <button disabled={busy || !apiKey.trim()} onClick={() => void connectApiKey()}>{busy ? t.connecting : t.connectProvider}</button>
      </section>

      {message && <p className="onboarding-message success" aria-live="polite">{message}</p>}
      {error && <p className="onboarding-message error" role="alert">{error || t.error}</p>}
      <p className="security-note">{t.privacy}</p>
    </section>
  </main>;
}
