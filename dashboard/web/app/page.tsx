"use client";

import { useMemo, useState } from "react";

type Language = "en" | "pt";

const copy = {
  en: {
    eyebrow: "Local dashboard workspace",
    title: "What should your dashboard help you understand?",
    body: "Describe the outcome in your own words. The agent will ask one clear question at a time and will not assume missing requirements.",
    placeholder: "For example: I need to understand monthly sales and delayed orders.",
    formats: "Reference samples: Excel, PDF, PNG, JPEG, or SVG",
    privacy: "Your project stays on this computer. Confidential data is never saved without your explicit approval.",
    button: "Continue",
  },
  pt: {
    eyebrow: "Área de trabalho local",
    title: "O que o seu dashboard deve ajudar você a entender?",
    body: "Descreva o resultado com suas palavras. O agente fará uma pergunta clara por vez e não presumirá requisitos ausentes.",
    placeholder: "Exemplo: preciso entender as vendas mensais e os pedidos atrasados.",
    formats: "Amostras aceitas: Excel, PDF, PNG, JPEG ou SVG",
    privacy: "Seu projeto permanece neste computador. Dados confidenciais nunca são salvos sem sua aprovação explícita.",
    button: "Continuar",
  },
};

export default function SetupPage() {
  const [language, setLanguage] = useState<Language>("en");
  const [goal, setGoal] = useState("");
  const text = useMemo(() => copy[language], [language]);

  return (
    <main className="shell">
      <section className="panel" aria-labelledby="setup-title">
        <div className="language-switch" aria-label="Language">
          <button className={language === "en" ? "active" : ""} onClick={() => setLanguage("en")}>EN</button>
          <button className={language === "pt" ? "active" : ""} onClick={() => setLanguage("pt")}>PT</button>
        </div>
        <p className="eyebrow">{text.eyebrow}</p>
        <h1 id="setup-title">{text.title}</h1>
        <p className="intro">{text.body}</p>
        <label htmlFor="goal" className="sr-only">{text.title}</label>
        <textarea
          id="goal"
          value={goal}
          onChange={(event) => setGoal(event.target.value)}
          placeholder={text.placeholder}
          rows={5}
        />
        <div className="notes">
          <p>{text.formats}</p>
          <p>{text.privacy}</p>
        </div>
        <button className="primary" disabled={!goal.trim()}>{text.button}</button>
      </section>
    </main>
  );
}
