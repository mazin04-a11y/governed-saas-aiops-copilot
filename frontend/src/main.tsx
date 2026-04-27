import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  BarChart3,
  CheckCircle2,
  ClipboardList,
  FileText,
  Gauge,
  KeyRound,
  ShieldAlert,
} from "lucide-react";
import "./styles.css";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

type Incident = {
  id: number;
  incident_type: string;
  title: string;
  severity: string;
  status: string;
  evidence_ids: number[];
  occurrence_count: number;
  updated_at: string;
};

type Row = Record<string, unknown>;

type ApprovalRow = Row & {
  id: number;
  report_id: number;
  status: string;
  reviewer?: string | null;
  decision_reason?: string | null;
};

type ReportRow = Row & {
  id: number;
  incident_id: number;
  report_version: number;
  validation_status: string;
  human_approval_required: boolean;
  human_approved?: boolean | null;
  created_at: string;
};

const tabs = [
  { id: "overview", label: "Overview", icon: Gauge },
  { id: "metrics", label: "Metrics", icon: BarChart3 },
  { id: "security", label: "Security", icon: ShieldAlert },
  { id: "incidents", label: "Incidents", icon: Activity },
  { id: "reports", label: "AI Reports", icon: FileText },
  { id: "approvals", label: "Approvals", icon: CheckCircle2 },
  { id: "audit", label: "Audit", icon: ClipboardList },
] as const;

function App() {
  const [active, setActive] = useState<(typeof tabs)[number]["id"]>("overview");
  const [data, setData] = useState<Record<string, Row[]>>({});
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [apiKey, setApiKey] = useState("local-dev-ingest-key");
  const [message, setMessage] = useState("");
  const [evidenceTitle, setEvidenceTitle] = useState("");
  const [evidenceRows, setEvidenceRows] = useState<Row[]>([]);

  async function refresh() {
    const endpoints = ["metrics", "access-logs", "reports", "approvals", "audit-logs"];
    const loaded = await Promise.all(
      endpoints.map(async (name) => [name, await fetch(`${API_BASE}/${name}`, { headers: apiHeaders() }).then((r) => r.json()).catch(() => [])] as const),
    );
    setData(Object.fromEntries(loaded));
    setIncidents(await fetch(`${API_BASE}/incidents`, { headers: apiHeaders() }).then((r) => r.json()).catch(() => []));
  }

  useEffect(() => {
    refresh();
  }, []);

  const latestRisk = useMemo(() => incidents.filter((item) => item.status === "open").length, [incidents]);

  async function sendMetric() {
    const response = await fetch(`${API_BASE}/metrics/ingest`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-API-Key": apiKey },
      body: JSON.stringify({
        service_name: "checkout-api",
        cpu_usage: 94,
        memory_usage: 89,
        response_time_ms: 1280,
        error_rate: 7.2,
        status: "degraded",
      }),
    });
    setMessage(response.ok ? "Metric ingested and deterministic detection ran." : `Metric ingest failed: ${response.status}`);
    refresh();
  }

  async function sendFailedLogin() {
    for (let i = 0; i < 3; i += 1) {
      await fetch(`${API_BASE}/access-logs/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-API-Key": apiKey },
        body: JSON.stringify({ username: "security_user", action: "login", ip_address: "203.0.113.77", outcome: "failed" }),
      });
    }
    setMessage("Access logs ingested and identity-aware detection ran.");
    refresh();
  }

  async function createReport(incidentId: number) {
    const response = await fetch(`${API_BASE}/incidents/${incidentId}/reports`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ use_external_intel: true }),
    });
    setMessage(response.ok ? "LangGraph workflow saved a validated report." : `Report workflow failed: ${response.status}`);
    refresh();
  }

  async function decideApproval(approvalId: number, status: "approved" | "rejected") {
    const response = await fetch(`${API_BASE}/approvals/${approvalId}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        status,
        reviewer: "operator",
        decision_reason: status === "approved" ? "Approved from operator dashboard." : "Rejected from operator dashboard.",
      }),
    });
    setMessage(response.ok ? `Approval ${status}.` : `Approval decision failed: ${response.status}`);
    refresh();
  }

  async function showEvidence(kind: "incidents" | "reports", id: number) {
    const rows = await fetch(`${API_BASE}/${kind}/${id}/evidence`, { headers: apiHeaders() }).then((r) => r.json()).catch(() => []);
    setEvidenceTitle(`${kind === "incidents" ? "Incident" : "Report"} ${id} evidence`);
    setEvidenceRows(rows);
  }

  function apiHeaders() {
    return apiKey ? { "X-API-Key": apiKey } : undefined;
  }

  async function exportAuditCsv() {
    const response = await fetch(`${API_BASE}/audit-logs/export`, { headers: apiHeaders() });
    if (!response.ok) {
      setMessage(`Audit export failed: ${response.status}`);
      return;
    }
    const text = await response.text();
    const blob = new Blob([text], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "audit-logs.csv";
    link.click();
    URL.revokeObjectURL(url);
    setMessage("Audit CSV exported.");
  }

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brandMark">G</div>
          <div>
            <h1>Governed AIOps Copilot</h1>
            <p>Evidence first. Approval before risky action.</p>
          </div>
        </div>
        <nav>
          {tabs.map((tab) => {
            const Icon = tab.icon;
            return (
              <button className={active === tab.id ? "active" : ""} key={tab.id} onClick={() => setActive(tab.id)} title={tab.label}>
                <Icon size={18} />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </nav>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">Three-Layer Anatomy</p>
            <h2>Senses, nervous system, and governed brain</h2>
          </div>
          <label className="keyInput">
            <KeyRound size={16} />
            <input value={apiKey} onChange={(event) => setApiKey(event.target.value)} aria-label="Ingest API key" />
          </label>
        </header>

        {message && <div className="notice">{message}</div>}

        {active === "overview" && (
          <div className="overview">
            <Stat label="Open incidents" value={latestRisk} />
            <Stat label="Stored reports" value={data.reports?.length ?? 0} />
            <Stat label="Pending approvals" value={(data.approvals ?? []).filter((row) => row.status === "pending").length} />
            <div className="band">
              <h3>Operating principle</h3>
              <p>Raw code detects. LangGraph controls. CrewAI analyzes. OpenAI explains. Pydantic validates. Human approves. PostgreSQL audits.</p>
              <div className="actions">
                <button onClick={sendMetric}>Ingest degraded metric</button>
                <button onClick={sendFailedLogin}>Ingest failed logins</button>
              </div>
            </div>
          </div>
        )}

        {active === "metrics" && <Table title="Metrics" rows={data.metrics ?? []} />}
        {active === "security" && <Table title="Access Logs" rows={data["access-logs"] ?? []} />}
        {active === "incidents" && (
          <Incidents incidents={incidents} onCreateReport={createReport} onShowEvidence={showEvidence} />
        )}
        {active === "reports" && <Reports rows={(data.reports ?? []) as ReportRow[]} onShowEvidence={showEvidence} />}
        {active === "approvals" && (
          <Approvals rows={(data.approvals ?? []) as ApprovalRow[]} onDecision={decideApproval} />
        )}
        {active === "audit" && <Audit rows={data["audit-logs"] ?? []} onExport={exportAuditCsv} />}
        {evidenceTitle && (
          <EvidencePanel title={evidenceTitle} rows={evidenceRows} onClose={() => setEvidenceTitle("")} />
        )}
      </section>
    </main>
  );
}

function Audit({ rows, onExport }: { rows: Row[]; onExport: () => void }) {
  return (
    <section className="tableWrap">
      <div className="panelHeader">
        <h3>Audit Trail</h3>
        <button onClick={onExport}>Export CSV</button>
      </div>
      <TableBody rows={rows} />
    </section>
  );
}

function Incidents({
  incidents,
  onCreateReport,
  onShowEvidence,
}: {
  incidents: Incident[];
  onCreateReport: (id: number) => void;
  onShowEvidence: (kind: "incidents" | "reports", id: number) => void;
}) {
  return (
    <section className="list">
      <h3>Incidents</h3>
      {incidents.map((incident) => (
        <article className="item" key={incident.id}>
          <div>
            <strong>{incident.title}</strong>
            <p>{incident.incident_type} | {incident.severity} | evidence {incident.evidence_ids.join(", ")}</p>
          </div>
          <div className="decisionActions">
            <button onClick={() => onShowEvidence("incidents", incident.id)}>Evidence</button>
            <button onClick={() => onCreateReport(incident.id)}>Generate report</button>
          </div>
        </article>
      ))}
      {incidents.length === 0 && <Empty text="No incidents. Connect data through the protected ingestion API." />}
    </section>
  );
}

function Reports({ rows, onShowEvidence }: { rows: ReportRow[]; onShowEvidence: (kind: "incidents" | "reports", id: number) => void }) {
  return (
    <section className="list">
      <h3>AI Reports</h3>
      {rows.map((row) => (
        <article className="item" key={row.id}>
          <div>
            <strong>Report {row.id} v{row.report_version} for incident {row.incident_id}</strong>
            <p>{row.validation_status} | approval {row.human_approval_required ? "required" : "not required"} | created {row.created_at}</p>
          </div>
          <button onClick={() => onShowEvidence("reports", row.id)}>Evidence</button>
        </article>
      ))}
      {rows.length === 0 && <Empty text="No AI reports yet." />}
    </section>
  );
}

function EvidencePanel({ title, rows, onClose }: { title: string; rows: Row[]; onClose: () => void }) {
  return (
    <section className="evidencePanel">
      <div className="panelHeader">
        <h3>{title}</h3>
        <button onClick={onClose}>Close</button>
      </div>
      {rows.length === 0 ? (
        <Empty text="No evidence rows found." />
      ) : (
        rows.map((row) => (
          <article className="evidenceRow" key={String(row.id)}>
            <strong>{String(row.evidence_type ?? "evidence")}</strong>
            <p>{String(row.summary ?? "")}</p>
            <pre>{JSON.stringify(row.payload ?? row, null, 2)}</pre>
          </article>
        ))
      )}
    </section>
  );
}

function Approvals({ rows, onDecision }: { rows: ApprovalRow[]; onDecision: (id: number, status: "approved" | "rejected") => void }) {
  return (
    <section className="list">
      <h3>Approvals</h3>
      {rows.map((row) => (
        <article className="item approvalItem" key={row.id}>
          <div>
            <strong>Report {row.report_id}</strong>
            <p>Status {row.status}{row.reviewer ? ` | reviewer ${row.reviewer}` : ""}</p>
          </div>
          {row.status === "pending" ? (
            <div className="decisionActions">
              <button className="approve" onClick={() => onDecision(row.id, "approved")}>Approve</button>
              <button className="reject" onClick={() => onDecision(row.id, "rejected")}>Reject</button>
            </div>
          ) : (
            <span className="statusPill">{row.status}</span>
          )}
        </article>
      ))}
      {rows.length === 0 && <Empty text="No approval requests yet." />}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="stat">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="empty">{text}</p>;
}

function Table({ title, rows }: { title: string; rows: Row[] }) {
  return (
    <section className="tableWrap">
      <h3>{title}</h3>
      <TableBody rows={rows} />
    </section>
  );
}

function TableBody({ rows }: { rows: Row[] }) {
  const keys = rows[0] ? Object.keys(rows[0]).slice(0, 7) : [];
  return (
    <>
      {rows.length === 0 ? (
        <Empty text="No rows yet." />
      ) : (
        <table>
          <thead>
            <tr>{keys.map((key) => <th key={key}>{key}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index}>
                {keys.map((key) => <td key={key}>{formatCell(row[key])}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

function formatCell(value: unknown) {
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object" && value) return JSON.stringify(value);
  return String(value ?? "");
}

createRoot(document.getElementById("root")!).render(<App />);
