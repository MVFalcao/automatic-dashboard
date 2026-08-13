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
  if (language === "en") await page.getByRole("button", { name: "EN", exact: true }).click();
  const answers = language === "pt"
    ? ["Acompanhar resultados", "Equipe local", "Não", "Web, Excel e PDF", resolve(state, "projeto"), "Sim"]
    : ["Track outcomes", "Local team", "No", "Web, Excel and PDF", resolve(state, "project"), "Yes"];
  for (const [index, answer] of answers.entries()) {
    await page.locator("#answer").fill(answer);
    await page.getByLabel(language === "pt" ? /Esta resposta não é confidencial/ : /This answer is non-confidential/).check();
    await page.getByRole("button", { name: language === "pt" ? /Continuar|Concluir/ : /Continue|Finish/ }).click();
    if (index === answers.length - 2) {
      await expect(page.getByRole("heading", { name: language === "pt" ? "O que o agente entendeu" : "What I understood" })).toBeVisible();
      await expect(page.locator(".understanding-note")).toContainText(answer);
    }
    if (index < answers.length - 1) await expect(page.locator("#answer")).toHaveValue("");
  }
  await expect(page.getByRole("heading", { name: language === "pt" ? "Revisão sintética do dashboard" : "Synthetic dashboard review" })).toBeVisible();
  await expect(page.getByText(language === "pt" ? /servidor gerou este documento/ : /server generated this document/).first()).toBeVisible();
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
}

test("@en complete English journey across API restart", async ({ page }) => completeJourney(page, "en"));
test("@pt complete Portuguese journey across API restart", async ({ page }) => completeJourney(page, "pt"));
