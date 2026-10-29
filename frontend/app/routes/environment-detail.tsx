import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router";

const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:3001").replace(/\/$/, "");

type EnvironmentDetail = {
  id: string;
  name: string;
  status: string;
  cpu_quota: number;
  mem_limit: number;
  cpu_weight: number;
  io_limit_bps: number;
  anchor_pid: number | null;
  error_message: string | null;
};

type Job = { id: string; status: string; env_id: string; env_name: string; script_id: string; script_name: string };

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
  const label = normalized === "running" ? "ativo" : normalized === "completed" ? "concluído" : normalized === "failed" ? "falhou" : normalized === "terminated" ? "encerrado" : normalized === "error" ? "erro" : normalized === "deleting" ? "removendo" : normalized === "pending" ? "pendente" : "na fila";
  return <span className={`status status-${normalized}`}><i />{label}</span>;
}

export function meta() {
  return [{ title: "Environment · Runway" }];
}

export default function EnvironmentDetailPage() {
  const { environmentId = "" } = useParams();
  const [environment, setEnvironment] = useState<EnvironmentDetail | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [cpuQuota, setCpuQuota] = useState("");
  const [memoryLimit, setMemoryLimit] = useState("");
  const [cpuWeight, setCpuWeight] = useState("");
  const [ioLimit, setIoLimit] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ type: "error" | "success"; text: string } | null>(null);

  const loadEnvironment = useCallback(async () => {
    if (!environmentId) return;
    setLoading(true);
    try {
      const [environmentData, jobData] = await Promise.all([
        request<EnvironmentDetail>(`/environment/${environmentId}`),
        request<Job[]>(`/environment/${environmentId}/jobs`),
      ]);
      setEnvironment(environmentData);
      setJobs(jobData);
      setCpuQuota(String(environmentData.cpu_quota));
      setMemoryLimit(String(environmentData.mem_limit));
      setCpuWeight(String(environmentData.cpu_weight));
      setIoLimit(String(Math.round(environmentData.io_limit_bps / 1024 / 1024)));
    } catch (error) {
      setMessage({ type: "error", text: error instanceof Error ? error.message : "Não foi possível carregar o ambiente." });
    } finally {
      setLoading(false);
    }
  }, [environmentId]);

  useEffect(() => { void loadEnvironment(); }, [loadEnvironment]);

  async function updateLimits(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cpuQuotaValue = Number(cpuQuota);
    const memoryLimitValue = Number(memoryLimit);
    const cpuWeightValue = Number(cpuWeight);
    const ioLimitValue = Number(ioLimit);

    if (!Number.isInteger(cpuQuotaValue) || cpuQuotaValue < 1 || cpuQuotaValue > 100) {
      setMessage({ type: "error", text: "CPU must be an integer between 1% and 100%." });
      return;
    }
    if (!Number.isInteger(memoryLimitValue) || memoryLimitValue < 1 || memoryLimitValue > 16384) {
      setMessage({ type: "error", text: "Memory must be an integer between 1 MB and 16384 MB." });
      return;
    }
    if (!Number.isInteger(cpuWeightValue) || cpuWeightValue < 1 || cpuWeightValue > 1000) {
      setMessage({ type: "error", text: "CPU weight must be an integer between 1 and 1000." });
      return;
    }
    if (!Number.isSafeInteger(ioLimitValue) || ioLimitValue < 0) {
      setMessage({ type: "error", text: "I/O must be zero or a positive integer in MB/s." });
      return;
    }

    setSaving(true);
    try {
      const updated = await request<EnvironmentDetail>(`/environment/${environmentId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cpu_quota: cpuQuotaValue,
          mem_limit: memoryLimitValue,
          cpu_weight: cpuWeightValue,
          io_limit_bps: ioLimitValue * 1024 * 1024,
        }),
      });
      setEnvironment(updated);
      setMessage({ type: "success", text: "Limits updated in the environment runtime." });
    } catch (error) {
      setMessage({ type: "error", text: error instanceof Error ? error.message : "Não foi possível atualizar os limites." });
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="environment-detail-shell">
      <header className="detail-topbar">
        <Link to="/" className="back-link">← Overview</Link>
        <span className="live-indicator"><i /> local runtime</span>
      </header>

      <div className="detail-page">
        {loading ? <div className="detail-loading">Loading environment…</div> : !environment ? <div className="detail-loading">Environment unavailable.</div> : <>
          <div className="detail-heading">
            <div><p className="eyebrow">Environment</p><h1>{environment.name}</h1><p className="detail-id">{environment.id}</p></div>
            <StatusPill status={environment.status} />
          </div>

          {message && <div className={`notice notice-${message.type}`} role="status"><span>{message.type === "success" ? "✓" : "!"}</span>{message.text}<button onClick={() => setMessage(null)} aria-label="Close notification">×</button></div>}
          {environment.error_message && <div className="environment-error"><strong>Runtime error</strong><p>{environment.error_message}</p></div>}

          <div className="detail-grid">
            <section className="panel">
              <div className="panel-heading"><div><span className="section-kicker">Configuration</span><h2>Resource limits</h2></div></div>
              <form className="detail-form" onSubmit={updateLimits}>
                <label>CPU limit <span>(%)</span><input type="number" min="1" max="100" step="1" value={cpuQuota} onChange={(event) => setCpuQuota(event.target.value)} /></label>
                <label>Memory <span>(MB)</span><input type="number" min="1" max="16384" step="1" value={memoryLimit} onChange={(event) => setMemoryLimit(event.target.value)} /></label>
                <label>CPU weight<input type="number" min="1" max="1000" step="1" value={cpuWeight} onChange={(event) => setCpuWeight(event.target.value)} /></label>
                <label>I/O limit <span>(MB/s)</span><input type="number" min="0" step="1" value={ioLimit} onChange={(event) => setIoLimit(event.target.value)} /></label>
                <p>I/O 0 = unlimited</p>
                <button className="button button-lime" disabled={saving}>{saving ? "Saving…" : "Save limits"}</button>
              </form>
            </section>

            <section className="panel">
              <div className="panel-heading"><div><span className="section-kicker">Runtime</span><h2>Environment state</h2></div><StatusPill status={environment.status} /></div>
              <dl className="runtime-details">
                <div><dt>Status</dt><dd>{environment.status}</dd></div>
                <div><dt>Anchor PID</dt><dd>{environment.anchor_pid ?? "—"}</dd></div>
                <div><dt>Jobs</dt><dd>{jobs.length}</dd></div>
                <div><dt>I/O</dt><dd>{environment.io_limit_bps === 0 ? "unlimited" : `${Math.round(environment.io_limit_bps / 1024 / 1024)} MB/s`}</dd></div>
              </dl>
            </section>
          </div>

          <section className="panel detail-jobs-panel">
            <div className="panel-heading"><div><span className="section-kicker">Activity</span><h2>Jobs in this environment</h2></div><span className="muted">{jobs.length} total</span></div>
            {jobs.length === 0 ? <div className="empty-jobs">No jobs have run in this environment.</div> : <div className="jobs-table"><div className="table-header detail-job-columns"><span>Job ID</span><span>Script</span><span>Status</span></div>{jobs.map((job) => <div className="job-row detail-job-columns" key={job.id}><span className="job-id"><i />{job.id}</span><span className="job-script">{job.script_name}</span><StatusPill status={job.status} /></div>)}</div>}
          </section>
        </>}
      </div>
    </main>
  );
}
