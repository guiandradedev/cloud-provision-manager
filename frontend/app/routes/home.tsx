import { useCallback, useEffect, useMemo, useState } from "react";
import type { Route } from "./+types/home";

const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:3001").replace(/\/$/, "");

type Environment = { id: string; name: string };
type Job = { id: string; status: string };
type Log = { source: string; content: string; created_at: string };

const environmentFields = [
  { key: "name", label: "Nome do ambiente", placeholder: "ex.: staging-blue", type: "text" },
] as const;

export function meta({}: Route.MetaArgs) {
  return [
    { title: "Runway · Provision Manager" },
    { name: "description", content: "Execute scripts com segurança em ambientes isolados." },
  ];
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, options);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `A API respondeu com ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function StatusPill({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const label = normalized === "completed" ? "concluído" : normalized === "failed" ? "falhou" : normalized === "running" ? "executando" : "na fila";
  return <span className={`status status-${normalized}`}><i />{label}</span>;
}

export default function Home() {
  const [environments, setEnvironments] = useState<Environment[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [logs, setLogs] = useState<Log[]>([]);
  const [environmentName, setEnvironmentName] = useState("");
  const [selectedEnvironment, setSelectedEnvironment] = useState("");
  const [script, setScript] = useState<File | null>(null);
  const [showEnvironmentForm, setShowEnvironmentForm] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<{ type: "error" | "success"; text: string } | null>(null);

  const loadData = useCallback(async () => {
    try {
      const [environmentData, jobData] = await Promise.all([
        request<Environment[]>("/environment"),
        request<Job[]>("/jobs"),
      ]);
      setEnvironments(environmentData);
      setJobs(jobData);
      setSelectedEnvironment((current) => current || environmentData[0]?.id || "");
    } catch (error) {
      setMessage({ type: "error", text: error instanceof Error ? error.message : "Não foi possível carregar os dados." });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void loadData(); }, [loadData]);

  const refreshJob = useCallback(async (job: Job) => {
    try {
      const [status, output] = await Promise.all([
        request<Job>(`/jobs/${job.id}`),
        request<{ output: Log[] }>(`/jobs/${job.id}/output`),
      ]);
      setJobs((current) => current.map((item) => item.id === status.id ? status : item));
      setSelectedJob(status);
      setLogs(output.output);
    } catch (error) {
      setMessage({ type: "error", text: error instanceof Error ? error.message : "Não foi possível consultar o job." });
    }
  }, []);

  useEffect(() => {
    if (!selectedJob) return;
    void refreshJob(selectedJob);
    if (!["queued", "running"].includes(selectedJob.status)) return;
    const interval = window.setInterval(() => void refreshJob(selectedJob), 1800);
    return () => window.clearInterval(interval);
  }, [selectedJob, refreshJob]);

  const runningJobs = useMemo(() => jobs.filter((job) => ["queued", "running"].includes(job.status)).length, [jobs]);

  async function createEnvironment(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!environmentName.trim()) return;
    setSubmitting(true);
    try {
      const created = await request<Environment>("/environment", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: environmentName.trim() }),
      });
      setEnvironments((current) => [...current, created]);
      setSelectedEnvironment(created.id);
      setEnvironmentName("");
      setShowEnvironmentForm(false);
      setMessage({ type: "success", text: "Ambiente criado e pronto para receber jobs." });
    } catch (error) {
      setMessage({ type: "error", text: error instanceof Error ? error.message : "Não foi possível criar o ambiente." });
    } finally { setSubmitting(false); }
  }

  async function submitJob(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedEnvironment || !script) return;
    setSubmitting(true);
    const formData = new FormData();
    formData.append("env_id", selectedEnvironment);
    formData.append("script", script);
    try {
      const created = await request<Job>("/jobs", { method: "POST", body: formData });
      setJobs((current) => [created, ...current]);
      setSelectedJob(created);
      setScript(null);
      (event.currentTarget as HTMLFormElement).reset();
      setMessage({ type: "success", text: "Job enviado. Acompanhe a execução no terminal." });
    } catch (error) {
      setMessage({ type: "error", text: error instanceof Error ? error.message : "Não foi possível enviar o script." });
    } finally { setSubmitting(false); }
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand"><span className="brand-mark">↗</span><span>runway</span></div>
        <div className="workspace-switcher"><span className="workspace-dot" /> local workspace <span className="chevron">⌄</span></div>
        <nav>
          <p className="nav-label">Workspace</p>
          <a className="nav-item active" href="#overview"><span>⌁</span> Overview</a>
          <a className="nav-item" href="#environments"><span>◫</span> Environments <b>{environments.length}</b></a>
          <a className="nav-item" href="#jobs"><span>▷</span> Jobs <b>{runningJobs || jobs.length}</b></a>
        </nav>
        <div className="sidebar-footer"><span className="connection-dot" /> API connected<div className="api-url">{API_URL.replace(/^https?:\/\//, "")}</div></div>
      </aside>

      <section className="content">
        <header className="topbar"><div className="breadcrumb">Workspace <span>/</span> Overview</div><div className="top-actions"><span className="live-indicator"><i /> live</span><button className="icon-button" aria-label="Settings">⚙</button><div className="avatar">A</div></div></header>

        <div className="page">
          <div className="page-heading"><div><p className="eyebrow">Control plane</p><h1>Ship work, not setup.</h1><p className="lede">Create an environment, drop in a script, and watch it run.</p></div><div className="date-stamp">OCT 08, 2026<br /><span>LOCAL RUNTIME</span></div></div>

          {message && <div className={`notice notice-${message.type}`} role="status"><span>{message.type === "success" ? "✓" : "!"}</span>{message.text}<button onClick={() => setMessage(null)} aria-label="Close notification">×</button></div>}

          <div className="metric-row">
            <div className="metric-card"><span>Environments</span><strong>{environments.length.toString().padStart(2, "0")}</strong><small>available now</small></div>
            <div className="metric-card accent"><span>Active jobs</span><strong>{runningJobs.toString().padStart(2, "0")}</strong><small>in the queue or running</small></div>
            <div className="metric-card"><span>Total jobs</span><strong>{jobs.length.toString().padStart(2, "0")}</strong><small>across this workspace</small></div>
          </div>

          <div className="main-grid">
            <section className="panel environments-panel" id="environments">
              <div className="panel-heading"><div><span className="section-kicker">01 / spaces</span><h2>Environments</h2></div><button className="button button-dark" onClick={() => setShowEnvironmentForm((value) => !value)}>+ New environment</button></div>
              {showEnvironmentForm && <form className="inline-form" onSubmit={createEnvironment}><label htmlFor="environment-name">{environmentFields[0].label}</label><div className="form-row"><input id="environment-name" value={environmentName} onChange={(event) => setEnvironmentName(event.target.value)} placeholder={environmentFields[0].placeholder} autoFocus /><button className="button button-lime" disabled={submitting}>{submitting ? "Creating…" : "Create"}</button></div></form>}
              {loading ? <div className="empty-state">Loading workspace…</div> : environments.length === 0 ? <div className="empty-state"><div className="empty-icon">⌁</div><strong>No environments yet</strong><span>Create your first space to start running scripts.</span><button className="text-button" onClick={() => setShowEnvironmentForm(true)}>Create an environment <span>↗</span></button></div> : <div className="environment-list">{environments.map((environment, index) => <button key={environment.id} className={`environment-row ${selectedEnvironment === environment.id ? "selected" : ""}`} onClick={() => setSelectedEnvironment(environment.id)}><span className="env-number">{String(index + 1).padStart(2, "0")}</span><span className="env-icon">⌂</span><span className="env-name">{environment.name}</span><span className="env-id">{environment.id.slice(0, 8)}</span><span className="row-arrow">↗</span></button>)}</div>}
            </section>

            <section className="panel launch-panel" id="jobs">
              <div className="panel-heading"><div><span className="section-kicker">02 / dispatch</span><h2>Run a job</h2></div><span className="file-type">.SH ONLY</span></div>
              <form onSubmit={submitJob} className="job-form">
                <label htmlFor="environment-select">Target environment</label>
                <select id="environment-select" value={selectedEnvironment} onChange={(event) => setSelectedEnvironment(event.target.value)} disabled={environments.length === 0}><option value="">Select an environment</option>{environments.map((environment) => <option key={environment.id} value={environment.id}>{environment.name}</option>)}</select>
                <label className={`drop-zone ${script ? "has-file" : ""}`} htmlFor="script-upload"><input id="script-upload" type="file" accept=".sh" onChange={(event) => setScript(event.target.files?.[0] || null)} /><span className="upload-symbol">{script ? "✓" : "↑"}</span><strong>{script ? script.name : "Drop your shell script here"}</strong><small>{script ? `${(script.size / 1024).toFixed(1)} KB · ready to run` : "or click to browse · UTF-8 .sh files"}</small></label>
                <button className="button button-lime launch-button" disabled={submitting || !selectedEnvironment || !script}>{submitting ? "Dispatching…" : "Dispatch job"}<span>↗</span></button>
              </form>
            </section>
          </div>

          <section className="panel jobs-panel">
            <div className="panel-heading"><div><span className="section-kicker">03 / activity</span><h2>Recent jobs</h2></div><span className="muted">{jobs.length} total</span></div>
            {jobs.length === 0 ? <div className="empty-jobs">Jobs will appear here after your first dispatch.</div> : <div className="jobs-table"><div className="table-header"><span>Job ID</span><span>Status</span><span>Action</span></div>{jobs.map((job) => <button key={job.id} className={`job-row ${selectedJob?.id === job.id ? "selected" : ""}`} onClick={() => void refreshJob(job)}><span className="job-id"><i />{job.id.slice(0, 12)}…</span><StatusPill status={job.status} /><span className="view-job">View output ↗</span></button>)}</div>}
          </section>

          {selectedJob && <section className="panel terminal-panel"><div className="terminal-heading"><div><span className="section-kicker">Job output</span><h2>{selectedJob.id.slice(0, 18)}…</h2></div><StatusPill status={selectedJob.status} /></div><div className="terminal"><div className="terminal-bar"><span /><span /><span /> <small>stdout / stderr</small></div>{logs.length === 0 ? <div className="terminal-empty">Waiting for output<span className="cursor">_</span></div> : logs.map((log, index) => <div className="log-line" key={`${log.created_at}-${index}`}><time>{new Date(log.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time><b className={log.source === "stderr" ? "stderr" : ""}>{log.source}</b><code>{log.content}</code></div>)}</div></section>}
        </div>
      </section>
    </main>
  );
}
