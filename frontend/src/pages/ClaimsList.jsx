import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../api";

const STATUS_OPTIONS = [
  "", "INGESTED", "VALIDATING", "VALIDATED", "VALIDATION_HOLD",
  "PRICING", "PRICED", "PRICING_HOLD", "PENDING_APPROVAL",
  "APPROVED", "DENIED", "PENDED",
  "PENDING_PAYMENT_APPROVAL", "PAYMENT_APPROVED", "PAYMENT_SCHEDULED",
  "PAID", "PAYMENT_HOLD",
];

export default function ClaimsList() {
  const [claims, setClaims] = useState([]);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    setError("");
    const query = status ? `?status=${status}` : "";
    apiFetch(`/claims/${query}`)
      .then(setClaims)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [status]);

  return (
    <div className="page">
      <div className="page-header">
        <h1>Claims List</h1>
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s === "" ? "All statuses" : s}
            </option>
          ))}
        </select>
      </div>

      {error && <div className="error-text">{error}</div>}
      {loading ? (
        <p>Loading...</p>
      ) : (
        <table className="claims-table">
          <thead>
            <tr>
              <th>Claim #</th>
              <th>Provider</th>
              <th>Member</th>
              <th>Date of Service</th>
              <th>Amount</th>
              <th>Status</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {claims.map((c) => (
              <tr key={c.id}>
                <td>
                  <Link to={`/claims/${c.id}`}>{c.claim_number}</Link>
                </td>
                <td>{c.provider_name}</td>
                <td>{c.member_name}</td>
                <td>{c.date_of_service}</td>
                <td>{c.total_claim_amount}</td>
                <td>
                  <span className={`status-badge status-${c.status.toLowerCase()}`}>{c.status}</span>
                </td>
                <td>{new Date(c.updated_at).toLocaleString()}</td>
              </tr>
            ))}
            {claims.length === 0 && (
              <tr>
                <td colSpan={7}>No claims found.</td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}