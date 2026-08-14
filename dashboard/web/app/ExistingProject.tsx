"use client";

import ProjectOperations from "./ProjectOperations";

type Language = "en" | "pt";
type Project = {
  id: string;
  name: string;
  project_directory: string;
  outputs: string[];
  language: Language;
  active_specification_version: number;
};
type Specification = {
  title: string;
  fields: Array<{ id: string; label: string }>;
  outputs: { enabled: string[] };
};

export type ExistingProjectWorkspace = { project: Project; specification: Specification };

export default function ExistingProject({ workspace, language, onBack }: { workspace: ExistingProjectWorkspace; language: Language; onBack: () => void }) {
  const { project, specification } = workspace;
  return <main className="shell">
    <section className="panel project-workspace" aria-labelledby="current-project-title">
      <button onClick={onBack}>{language === "pt" ? "← Voltar aos projetos" : "← Back to projects"}</button>
      <p className="eyebrow">{language === "pt" ? "Projeto atual" : "Current project"}</p>
      <h1 id="current-project-title">{project.name}</h1>
      <p>{specification.title} · v{project.active_specification_version}</p>
      <code>{project.project_directory}</code>
      <ProjectOperations
        language={language}
        projectId={project.id}
        projectDirectory={project.project_directory}
        outputs={specification.outputs.enabled}
        fields={specification.fields}
      />
    </section>
  </main>;
}
