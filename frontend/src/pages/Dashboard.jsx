import { useEffect, useState } from "react";
import { apiFetch } from "../api";

const STATUS_OPTIONS = [
  "", "INGESTED", "VALIDATING", "VALIDATED", "VALIDATION_HOLD",
  "PRICING", "PRICED", "PRICING_HOLD", "PENDING_APPROVAL",
  "APPROVED", "DENIED", "PENDED",
  "PENDING_PAYMENT_APPROVAL", "PAYMENT_APPROVED", "PAYMENT_SCHEDULED",
  "PAID", "PAYMENT_HOLD",
];

function StatCard({ label, value }) {
  return (
    <div className="stat-card">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

function DateCountList({ rows }) {
  if (!rows || rows.length === 0) return <p className="muted">No events in range.</p>;
  return (
    <ul className="simple-list">
      {rows.map((r, i) => (
        <li key={i}><span>{r.day}</span><span>{r.count}</span></li>
      ))}
    </ul>
  );
}

export default function Dashboard() {
  const [filters, setFilters] = useState({
    start_date: "", end_date: "", status: "", provider: "", member: "", claim_type: "",
  });
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  function load() {
    setLoading(true);
    setError("");
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => { if (v) params.set(k, v); });
    const query = params.toString() ? `?${params.toString()}` : "";
    apiFetch(`/analytics/dashboard/${query}`)
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function handleFilterSubmit(e) {
    e.preventDefault();
    load();
  }

  return (
    <div className="page">
      <h1>Analytics Dashboard</h1>

      <form className="filter-bar" onSubmit={handleFilterSubmit}>
        <label>Start date
          <input type="date" value={filters.start_date}
            onChange={(e) => setFilters({ ...filters, start_date: e.target.value })} />
        </label>
        <label>End date
          <input type="date" value={filters.end_date}
            onChange={(e) => setFilters({ ...filters, end_date: e.target.value })} />
        </label>
        <label>Status
          <select value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}>
            {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s || "All"}</option>)}
          </select>
        </label>
        <label>Provider ID
          <input value={filters.provider} onChange={(e) => setFilters({ ...filters, provider: e.target.value })} />
        </label>
        <label>Member ID
          <input value={filters.member} onChange={(e) => setFilters({ ...filters, member: e.target.value })} />
        </label>
        <button type="submit">Apply Filters</button>
      </form>

      {error && <div className="error-text">{error}</div>}
      {loading && <p>Loading...</p>}

      {data && (
        <>
          <div className="stat-grid">
            <StatCard label="Total Claims Received" value={data.total_claims_received} />
            <StatCard label="Pending Approval" value={data.claims_pending_approval} />
            <StatCard label="Payment Volume" value={data.payment_volume} />
            <StatCard label="Payment Amount (Total)" value={data.payment_amount_total} />
            <StatCard label="Avg Turnaround (hrs)" value={data.avg_turnaround_hours ?? "—"} />
          </div>

          <div className="detail-grid">
            <section className="card">
              <h3>Claims by Status</h3>
              <ul className="simple-list">
                {data.claims_by_status.map((r, i) => (
                  <li key={i}><span>{r.status}</span><span>{r.count}</span></li>
                ))}
              </ul>
            </section>

            <section className="card">
              <h3>Approved by Date</h3>
              <DateCountList rows={data.claims_approved_by_date} />
            </section>

            <section className="card">
              <h3>Denied by Date</h3>
              <DateCountList rows={data.claims_denied_by_date} />
            </section>

            <section className="card">
              <h3>Pended by Date</h3>
              <DateCountList rows={data.claims_pended_by_date} />
            </section>

            <section className="card">
              <h3>Payment Amount by Month</h3>
              {data.payment_amount_by_period.length === 0 ? (
                <p className="muted">No payments in range.</p>
              ) : (
                <ul className="simple-list">
                  {data.payment_amount_by_period.map((r, i) => (
                    <li key={i}><span>{r.period ? new Date(r.period).toLocaleDateString(undefined, { year: "numeric", month: "short" }) : "—"}</span><span>{r.total}</span></li>
                  ))}
                </ul>
              )}
            </section>

            <section className="card">
              <h3>Provider Analysis</h3>
              <table className="mini-table">
                <thead><tr><th>Provider</th><th>Claims</th><th>Billed</th><th>Approved</th></tr></thead>
                <tbody>
                  {data.provider_analysis.map((r, i) => (
                    <tr key={i}>
                      <td>{r["provider__name"]} ({r["provider__provider_id"]})</td>
                      <td>{r.claim_count}</td>
                      <td>{r.total_billed}</td>
                      <td>{r.total_approved ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <section className="card">
              <h3>Member Analysis</h3>
              <table className="mini-table">
                <thead><tr><th>Member</th><th>Claims</th><th>Billed</th><th>Approved</th></tr></thead>
                <tbody>
                  {data.member_analysis.map((r, i) => (
                    <tr key={i}>
                      <td>{r["member__name"]} ({r["member__member_id"]})</td>
                      <td>{r.claim_count}</td>
                      <td>{r.total_billed}</td>
                      <td>{r.total_approved ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          </div>
        </>
      )}
    </div>
  );
}