import { expect, test } from "@playwright/test";
import { ChildProcess, spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";

const repository = resolve(process.cwd(), "../..");
const state = mkdtempSync(resolve(tmpdir(), "dashboard-e2e-"));
let api: ChildProcess | null = null;

async function waitForApi() {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    try { if ((await fetch("http://127.0.0.1:8000/health")).ok) return; } catch { /* booting */ }
    await new Promise((resolveWait) => setTimeout(resolveWait, 100));
  }
  throw new Error("API did not start");
}

async function startApi() {
  api = spawn(resolve(repository, ".venv/bin/python"), ["-m", "uvicorn", "dashboard.api.main:app", "--host", "127.0.0.1", "--port", "8000"], {
    cwd: repository,
    env: {
      ...process.env,
      DASHBOARD_ENFORCE_LOCAL_SECURITY: "true",
      DASHBOARD_LOCAL_AUTH_TOKEN: "e2e-token",
      DASHBOARD_ALLOWED_ORIGINS: "http://127.0.0.1:3000",
      DASHBOARD_INTAKE_STATE: resolve(state, "intake.json"),
      DASHBOARD_APPROVAL_STATE: resolve(state, "approvals.json"),
      DASHBOARD_PROJECT_REGISTRY: resolve(state, "projects.json"),
      DASHBOARD_SCHEDULER_DB: resolve(state, "schedules.sqlite3"),
    },
    stdio: "inherit",
  });
  await waitForApi();
  const provider = await fetch("http://127.0.0.1:8000/api/providers/connect", {
    method: "POST",
    headers: { "Authorization": "Bearer e2e-token", "Content-Type": "application/json" },
    body: JSON.stringify({ connection: {
      provider: "codex",
      account_id: "synthetic-e2e",
      model: "gpt-5.5",
      auth_method: "oauth",
      credential: { backend: "hermes-auth-store", provider: "openai-codex", account: "synthetic-e2e" },
      capabilities: ["conversation", "structured_output", "insights"],
      token_estimate: { input_tokens: 0, output_tokens: 0 },
    } }),
  });
  if (!provider.ok) throw new Error(`Unable to register the synthetic E2E provider: ${provider.status}`);
}

async function restartApi() {
  api?.kill("SIGTERM");
  await new Promise((resolveWait) => api?.once("exit", resolveWait));
  await startApi();
}

test.beforeAll(startApi);
test.afterAll(async () => {
  api?.kill("SIGTERM");
  await new Promise((resolveWait) => api?.once("exit", resolveWait));
});

async function completeJourney(page: import("@playwright/test").Page, language: "en" | "pt") {
  await page.goto("/");
  await page.getByRole("button", { name: language === "pt" ? "PT" : "EN", exact: true }).click();
  await expect(page.getByRole("heading", { name: language === "pt" ? "Seus projetos de dashboard" : "Your dashboard projects" })).toBeVisible();
  await page.getByRole("button", { name: language === "pt" ? "Criar novo projeto" : "Create new project" }).click();
  const answers = language === "pt"
    ? ["Acompanhar resultados", "Equipe local", "Não", "Web, Excel e PDF", resolve(state, "projeto"), "Sim"]
    : ["Track outcomes", "Local team", "No", "Web, Excel and PDF", resolve(state, "project"), "Yes"];
  for (const [index, answer] of answers.entries()) {
    await page.locator("#answer").fill(answer);
    await page.getByLabel(language === "pt" ? /Esta resposta não é confidencial/ : /This answer is non-confidential/).check();
    await page.getByRole("button", { name: language === "pt" ? /Continuar|Concluir/ : /Continue|Finish/ }).click();
    if (index === answers.length - 2) {
      await expect(page.getByRole("heading", { name: language === "pt" ? "O que o agente entendeu" : "What the agent understood" })).toBeVisible();
      await expect(page.locator(".understanding-note")).toContainText(answer);
    }
    if (index < answers.length - 1) await expect(page.locator("#answer")).toHaveValue("");
  }
  await expect(page.getByRole("heading", { name: language === "pt" ? "Revisão sintética do dashboard" : "Synthetic dashboard review" })).toBeVisible();
  await expect(page.getByText(language === "pt" ? /servidor gerou este documento/ : /server generated this document/).first()).toBeVisible();
  await expect(page.getByText(language === "pt" ? "Conectar um provider de IA" : "Connect an AI provider", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: language === "pt" ? "Pedir ao Hermes" : "Ask Hermes" })).toBeDisabled();
  const url = page.url();
  await restartApi();
  await page.goto(url);
  await expect(page.getByRole("heading", { name: language === "pt" ? "Revisão sintética do dashboard" : "Synthetic dashboard review" })).toBeVisible();
  const approve = language === "pt" ? "Aprovar seção" : "Approve section";
  await expect(page.locator(".review-section")).toHaveCount(3);
  for (const [index, section] of (await page.locator(".review-section").all()).entries()) {
    await section.getByRole("button", { name: approve }).click();
    await expect(page.locator(".status.approved")).toHaveCount(index + 1);
  }
  await expect(page.locator(".status.approved")).toHaveCount(3);
  await page.getByRole("button", { name: language === "pt" ? "Criar projeto e ativar especificação aprovada" : "Create project and activate approved specification" }).click();
  await expect(page.getByRole("heading", { name: language === "pt" ? "Operações do projeto" : "Project operations" })).toBeVisible();
  await restartApi();
  await page.goto(url);
  await expect(page.getByRole("heading", { name: language === "pt" ? "Operações do projeto" : "Project operations" })).toBeVisible();
  await page.getByLabel(language === "pt" ? "Cor de destaque" : "Accent color").fill("#345678");
  await page.getByRole("button", { name: language === "pt" ? "Salvar controles como rascunho" : "Save controls as draft" }).click();
  await expect(page.getByText(/v1/)).toBeVisible();
  await expect(page.getByText(language === "pt" ? /especificação ativa aprovada não foi alterada/ : /active approved specification is unchanged/)).toBeVisible();
  await page.goto("/");
  await expect(page.getByRole("heading", { name: language === "pt" ? "Seus projetos de dashboard" : "Your dashboard projects" })).toBeVisible();
  const projectName = language === "pt" ? "Acompanhar resultados" : "Track outcomes";
  const projectCard = page.locator(".project-card").filter({ hasText: projectName });
  await expect(projectCard).toBeVisible();
  await projectCard.getByRole("button", { name: language === "pt" ? "Abrir projeto" : "Open project" }).click();
  await expect(page.getByRole("heading", { name: language === "pt" ? "Operações do projeto" : "Project operations" })).toBeVisible();
  await expect(page.getByText(language === "pt" ? "Configuração de provedor" : "Provider setup", { exact: true })).toHaveCount(0);
  await page.route("**/backend/api/projects/*/revisions", async (route) => {
    await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({
      id: "synthetic-revision", base_version: 1, mode: "update", hermes_response: language === "pt" ? "Reorganizei os cartões e preservei os cálculos aprovados." : "I reorganized the cards and preserved the approved calculations.", active_specification_unchanged: true,
      specification: { title: projectName, fields: [], metrics: [], outputs: { enabled: ["web"] }, style: { palette: ["#1D4ED8"] }, sections: [{ id: "summary", title: language === "pt" ? "Resumo" : "Summary", kind: "summary", metric_ids: [], field_ids: [] }] },
      approval: { approval_id: "00000000-0000-0000-0000-000000000099", ready_to_activate: false, sections: { summary: { section_id: "summary", status: "pending" } } },
      preview: { synthetic: true, metrics: { records: 24 }, records: [] },
    }) });
  });
  await page.getByText(language === "pt" ? "Atualizar dashboard com o Hermes" : "Update dashboard with Hermes", { exact: true }).click();
  await page.getByLabel(language === "pt" ? "O que o Hermes deve alterar?" : "What should Hermes change?").fill(language === "pt" ? "Use cartões menores" : "Use smaller cards");
  await page.getByLabel(language === "pt" ? "Confirmo que esta instrução não é confidencial" : "I confirm this instruction is non-confidential").check();
  await page.getByRole("button", { name: language === "pt" ? "Pedir ao Hermes para atualizar" : "Ask Hermes to update" }).click();
  await expect(page.getByText(language === "pt" ? "Reorganizei os cartões e preservei os cálculos aprovados." : "I reorganized the cards and preserved the approved calculations.")).toBeVisible();
  await expect(page.getByRole("button", { name: language === "pt" ? "Voltar ao projeto" : "Return to project" })).toBeVisible();
  await page.getByRole("button", { name: language === "pt" ? "Voltar ao projeto" : "Return to project" }).click();
  await expect(page.getByRole("heading", { name: projectName })).toBeVisible();
}

async function verifyProviderOnboarding(page: import("@playwright/test").Page, language: "en" | "pt") {
  await page.route("**/backend/api/hermes/status", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ready: true, provider_ready: false }) });
  });
  await page.route("**/backend/api/providers/oauth/codex/start", async (route) => {
    await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({
      session_id: "synthetic-onboarding", project_id: null, status: "pending", verification_url: null,
      user_code: "ABCD-EFGH", expires_in: 900, error: null, recoverable: false, remediation: null,
      provider: "openai-codex", model: "gpt-5.5", compatible: false,
    }) });
  });
  await page.route("**/backend/api/providers/oauth/codex/synthetic-onboarding", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      session_id: "synthetic-onboarding", project_id: null, status: "connected", verification_url: null,
      user_code: null, expires_in: 850, error: null, recoverable: false, remediation: null,
      provider: "openai-codex", model: "gpt-5.5", compatible: true,
    }) });
  });
  await page.goto("/");
  await page.getByRole("button", { name: language === "pt" ? "PT" : "EN", exact: true }).click();
  await expect(page.getByRole("heading", { name: language === "pt" ? "Conecte seu agente de IA" : "Connect your AI agent" })).toBeVisible();
  await expect(page.getByRole("button", { name: language === "pt" ? "Conectar Codex pelo navegador" : "Connect Codex in browser" })).toBeVisible();
  await page.getByRole("button", { name: language === "pt" ? "Conectar Codex pelo navegador" : "Connect Codex in browser" }).click();
  await expect(page.getByRole("heading", { name: language === "pt" ? "Seus projetos de dashboard" : "Your dashboard projects" })).toBeVisible();
}

test("@en agent connection is required before projects in English", async ({ page }) => verifyProviderOnboarding(page, "en"));
test("@pt conexão do agente é obrigatória antes dos projetos", async ({ page }) => verifyProviderOnboarding(page, "pt"));
test("@en complete English journey across API restart", async ({ page }) => completeJourney(page, "en"));
test("@pt complete Portuguese journey across API restart", async ({ page }) => completeJourney(page, "pt"));
