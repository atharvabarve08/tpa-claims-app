import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { apiFetch, getUser } from "../api";

function ActionBox({ title, children }) {
  return (
    <div className="action-box">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

export default function ClaimDetail() {
  const { id } = useParams();
  const [claim, setClaim] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [risk, setRisk] = useState(null);
  const [riskError, setRiskError] = useState("");
  const [comment, setComment] = useState("");
  const [paymentForm, setPaymentForm] = useState({
    method: "ACH",
    scheduled_payment_date: "",
    reference_number: "",
  });
  const [editForm, setEditForm] = useState(null); // null until "Edit Claim" is opened
  const [retryMsg, setRetryMsg] = useState("");

  const user = getUser();
  const role = user?.role;
  const canApprove = role === "CLAIMS_APPROVER" || role === "TPA_MANAGER";
  const canSubmit = role === "CLAIMS_SUBMITTER" || role === "TPA_MANAGER";
  const isOnAnyHold = claim => claim && (claim.status === "VALIDATION_HOLD" || claim.status === "PRICING_HOLD" || claim.status === "PAYMENT_HOLD");
  const isOnEditableHold = claim => claim && (claim.status === "VALIDATION_HOLD" || claim.status === "PRICING_HOLD");

  function loadClaim() {
    setError("");
    apiFetch(`/claims/${id}/risk-score/`)
      .then((r) => { setRisk(r); setRiskError(""); })
      .catch((err) => { setRisk(null); setRiskError(err.message); });
    return apiFetch(`/claims/${id}/`)
      .then(setClaim)
      .catch((err) => setError(err.message));
  }

  useEffect(() => {
    loadClaim();
  }, [id]);

  async function runAction(path, body) {
    setBusy(true);
    setError("");
    try {
      await apiFetch(path, { method: "POST", body });
      await loadClaim();
      setComment("");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleRetry() {
    setBusy(true);
    setRetryMsg("");
    setError("");
    try {
      const res = await apiFetch(`/claims/${id}/retry/`, { method: "POST", body: {} });
      setRetryMsg(res.detail || "Retry queued.");
      setTimeout(loadClaim, 1500); // give the worker a moment before refreshing
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function openEditForm() {
    setEditForm({
      authorization_number: claim.authorization_number || "",
      claim_type: claim.claim_type || "",
      service_lines: claim.service_lines.map((sl) => ({
        cpt_code: sl.cpt_code, description: sl.description, units: sl.units, billed_amount: sl.billed_amount,
      })),
    });
  }

  function updateEditLine(i, field, value) {
    setEditForm({
      ...editForm,
      service_lines: editForm.service_lines.map((l, idx) => (idx === i ? { ...l, [field]: value } : l)),
    });
  }

  async function handleEditSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await apiFetch(`/claims/${id}/edit/`, { method: "PATCH", body: editForm });
      setEditForm(null);
      setRetryMsg("Saved — retry queued automatically.");
      setTimeout(loadClaim, 1500);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (error && !claim) return <div className="page"><p className="error-text">{error}</p></div>;
  if (!claim) return <div className="page"><p>Loading...</p></div>;

  // Once a claim has a real outcome, show it next to the prediction so the
  // two can be compared. The prediction only uses intake data, so it can't
  // foresee problems caused by later steps (e.g. a blank payment reference).
  const actualProblem = claim.status === "DENIED" || claim.status.endsWith("_HOLD");
  const actualClean = claim.status === "PAID";
  const outcomeKnown = actualProblem || actualClean;
  let verdict = "";
  if (risk && outcomeKnown) {
    const predictedProblem = risk.level !== "LOW";
    if (actualProblem && predictedProblem) verdict = "The model flagged this claim correctly.";
    else if (actualProblem) verdict = "The model did not flag this claim. It only sees intake data, so problems from later steps (like a missing payment reference) are invisible to it.";
    else if (!predictedProblem) verdict = "The model called this claim correctly.";
    else verdict = "The model over-estimated the risk for this claim.";
  }

  return (
    <div className="page">
      <Link to="/">&larr; Back to Claims List</Link>
      <div className="page-header">
        <h1>{claim.claim_number}</h1>
        <span className={`status-badge status-${claim.status.toLowerCase()}`}>{claim.status}</span>
      </div>

      {error && <div className="error-text">{error}</div>}
      {claim.hold_reason && claim.status.endsWith("_HOLD") && (
        <div className="hold-banner"><strong>Hold reason:</strong> {claim.hold_reason}</div>
      )}

      <section className="card risk-card">
        <h3>Denial / Hold Risk</h3>
        {risk ? (
          <>
            <div className="risk-row">
              <span className="risk-label">
                {outcomeKnown ? "Predicted from intake data:" : "Predicted:"}
              </span>
              <span className={`risk-badge risk-${risk.level.toLowerCase()}`}>
                {risk.level} &middot; {Math.round(risk.probability * 100)}%
              </span>
              {outcomeKnown && (
                <>
                  <span className="risk-label">Actual outcome:</span>
                  <span className={`status-badge status-${claim.status.toLowerCase()}`}>{claim.status}</span>
                </>
              )}
            </div>
            {!outcomeKnown && (
              <p className="muted">Estimated chance this claim is denied or put on hold.</p>
            )}
            {verdict && <p className="risk-verdict">{verdict}</p>}
            {risk.reasons.length > 0 && (
              <ul className="risk-reasons">
                {risk.reasons.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            )}
          </>
        ) : (
          <p className="muted">Risk score unavailable{riskError ? `: ${riskError}` : "."}</p>
        )}
      </section>

      <div className="detail-grid">
        <section className="card">
          <h3>Claim Info</h3>
          <p><strong>Provider:</strong> {claim.provider.name} ({claim.provider.provider_id})</p>
          <p><strong>Member:</strong> {claim.member.name} ({claim.member.member_id})</p>
          <p><strong>Date of Service:</strong> {claim.date_of_service}</p>
          <p><strong>Authorization #:</strong> {claim.authorization_number || "—"}</p>
          <p><strong>Billed:</strong> {claim.total_claim_amount} &nbsp; <strong>Approved:</strong> {claim.total_approved_amount ?? "—"}</p>
        </section>

        <section className="card">
          <h3>Service Lines</h3>
          <table className="mini-table">
            <thead><tr><th>CPT</th><th>Units</th><th>Billed</th><th>Allowed</th><th>Approved</th></tr></thead>
            <tbody>
              {claim.service_lines.map((sl) => (
                <tr key={sl.id}>
                  <td>{sl.cpt_code}</td><td>{sl.units}</td><td>{sl.billed_amount}</td>
                  <td>{sl.allowed_amount ?? "—"}</td><td>{sl.approved_amount ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="card">
          <h3>Status History</h3>
          <ul className="history-list">
            {claim.status_history.map((h, i) => (
              <li key={i}>
                <span className="history-arrow">{h.from_status || "—"} → {h.to_status}</span>
                <span className="history-reason">{h.reason}</span>
                <span className="history-meta">{h.actor} · {new Date(h.created_at).toLocaleString()}</span>
              </li>
            ))}
          </ul>
        </section>

        {claim.payments.length > 0 && (
          <section className="card">
            <h3>Payments</h3>
            {claim.payments.map((p) => (
              <div key={p.id} className="payment-row">
                <span>{p.method} · {p.amount} · ref {p.reference_number || "—"}</span>
                <span className={`status-badge status-${p.status.toLowerCase()}`}>{p.status}</span>
                {p.eop_text && <pre className="eop-text">{p.eop_text}</pre>}
              </div>
            ))}
          </section>
        )}
      </div>

      {/* --- Retry / Edit for held claims --- */}
      {canSubmit && isOnAnyHold(claim) && (
        <ActionBox title="This claim is on hold">
          <p className="muted">
            Fix the underlying issue, then retry. If the cause is on the claim itself
            (e.g. a missing authorization number), use Edit Claim below. If it's external
            (e.g. the provider or member needed to be reactivated), just use Retry Now.
          </p>
          <div className="button-row">
            <button disabled={busy} onClick={handleRetry}>Retry Now</button>
            {isOnEditableHold(claim) && !editForm && (
              <button disabled={busy} onClick={openEditForm}>Edit Claim</button>
            )}
          </div>
          {retryMsg && <p className="risk-verdict">{retryMsg}</p>}

          {editForm && (
            <form onSubmit={handleEditSubmit} className="edit-claim-form">
              <label>Authorization Number
                <input
                  value={editForm.authorization_number}
                  onChange={(e) => setEditForm({ ...editForm, authorization_number: e.target.value })}
                />
              </label>
              <label>Claim Type
                <input
                  value={editForm.claim_type}
                  onChange={(e) => setEditForm({ ...editForm, claim_type: e.target.value })}
                />
              </label>

              <h4>Service Lines</h4>
              {editForm.service_lines.map((l, i) => (
                <div key={i} className="line-row">
                  <input placeholder="CPT" required value={l.cpt_code}
                    onChange={(e) => updateEditLine(i, "cpt_code", e.target.value)} />
                  <input placeholder="Description" value={l.description}
                    onChange={(e) => updateEditLine(i, "description", e.target.value)} />
                  <input type="number" min="1" placeholder="Units" value={l.units}
                    onChange={(e) => updateEditLine(i, "units", e.target.value)} />
                  <input type="number" step="0.01" placeholder="Billed" required value={l.billed_amount}
                    onChange={(e) => updateEditLine(i, "billed_amount", e.target.value)} />
                </div>
              ))}
              <button type="button" className="link-button"
                onClick={() => setEditForm({ ...editForm, service_lines: [...editForm.service_lines, { cpt_code: "", description: "", units: 1, billed_amount: "" }] })}>
                + Add service line
              </button>

              <div className="button-row" style={{ marginTop: 12 }}>
                <button type="submit" disabled={busy}>Save &amp; Retry</button>
                <button type="button" disabled={busy} onClick={() => setEditForm(null)}>Cancel</button>
              </div>
            </form>
          )}
        </ActionBox>
      )}

      {/* --- Stage 4: Approval actions --- */}
      {canApprove && (claim.status === "PENDING_APPROVAL" || claim.status === "PENDED") && (
        <ActionBox title="Approval Decision">
          <textarea
            placeholder="Comment (denial reason, notes, etc.)"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          <div className="button-row">
            <button disabled={busy} onClick={() => runAction(`/claims/${id}/approve/`, { comment })}>Approve</button>
            <button disabled={busy} className="danger" onClick={() => runAction(`/claims/${id}/deny/`, { comment })}>Deny</button>
            <button disabled={busy} onClick={() => runAction(`/claims/${id}/pend/`, { comment })}>Pend</button>
          </div>
        </ActionBox>
      )}

      {/* --- Stage 5: Payment actions --- */}
      {canSubmit && claim.status === "APPROVED" && (
        <ActionBox title="Submit for Payment Approval">
          <button disabled={busy} onClick={() => runAction(`/claims/${id}/submit-payment-approval/`, {})}>
            Submit for Payment Approval
          </button>
        </ActionBox>
      )}

      {canApprove && claim.status === "PENDING_PAYMENT_APPROVAL" && (
        <ActionBox title="Payment Approval Decision">
          <textarea
            placeholder="Comment"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          <div className="button-row">
            <button disabled={busy} onClick={() => runAction(`/claims/${id}/approve-payment/`, { comment })}>Approve Payment</button>
            <button disabled={busy} className="danger" onClick={() => runAction(`/claims/${id}/hold-payment/`, { comment })}>Hold Payment</button>
          </div>
        </ActionBox>
      )}

      {canSubmit && claim.status === "PAYMENT_APPROVED" && (
        <ActionBox title="Schedule Payment">
          <div className="form-row">
            <label>
              Method
              <select
                value={paymentForm.method}
                onChange={(e) => setPaymentForm({ ...paymentForm, method: e.target.value })}
              >
                <option value="ACH">ACH</option>
                <option value="CHECK">Check</option>
              </select>
            </label>
            <label>
              Scheduled Date
              <input
                type="date"
                value={paymentForm.scheduled_payment_date}
                onChange={(e) => setPaymentForm({ ...paymentForm, scheduled_payment_date: e.target.value })}
              />
            </label>
            <label>
              Reference #
              <input
                value={paymentForm.reference_number}
                onChange={(e) => setPaymentForm({ ...paymentForm, reference_number: e.target.value })}
              />
            </label>
          </div>
          <button disabled={busy} onClick={() => runAction(`/claims/${id}/schedule-payment/`, paymentForm)}>
            Schedule Payment
          </button>
        </ActionBox>
      )}
    </div>
  );
}