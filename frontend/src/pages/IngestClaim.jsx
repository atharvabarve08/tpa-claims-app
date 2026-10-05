import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { apiFetch, getToken } from "../api";

const emptyLine = { cpt_code: "", description: "", units: 1, billed_amount: "" };

export default function IngestClaim() {
  const navigate = useNavigate();
  const [claim, setClaim] = useState({
    claim_number: "",
    claim_type: "",
    authorization_number: "",
    date_of_service: "",
  });
  const [provider, setProvider] = useState({ provider_id: "", name: "", is_active: true });
  const [member, setMember] = useState({
    member_id: "",
    name: "",
    membership_status: "ACTIVE",
    membership_effective_date: "",
  });
  const [lines, setLines] = useState([{ ...emptyLine }]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const total = lines.reduce((sum, l) => sum + (parseFloat(l.billed_amount) || 0), 0);

  const [ediFile, setEdiFile] = useState(null);
  const [ediResults, setEdiResults] = useState(null);
  const [ediError, setEdiError] = useState("");
  const [ediBusy, setEdiBusy] = useState(false);

  async function handleEdiUpload(e) {
    e.preventDefault();
    if (!ediFile) return;
    setEdiBusy(true);
    setEdiError("");
    setEdiResults(null);
    try {
      const formData = new FormData();
      formData.append("file", ediFile);
      const res = await fetch("http://127.0.0.1:8000/api/claims/ingest-edi837/", {
        method: "POST",
        headers: { Authorization: `Token ${getToken()}` },
        body: formData, // no Content-Type header — the browser sets the multipart boundary itself
      });
      const data = await res.json();
      if (!res.ok && res.status !== 207) {
        throw new Error(data.detail || "Upload failed.");
      }
      setEdiResults(data.results);
    } catch (err) {
      setEdiError(err.message);
    } finally {
      setEdiBusy(false);
    }
  }

  function updateLine(i, field, value) {
    setLines(lines.map((l, idx) => (idx === i ? { ...l, [field]: value } : l)));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const body = {
        ...claim,
        total_claim_amount: total,
        provider,
        member: {
          ...member,
          membership_effective_date: member.membership_effective_date || null,
        },
        service_lines: lines.map((l) => ({
          cpt_code: l.cpt_code,
          description: l.description,
          units: parseInt(l.units, 10) || 1,
          billed_amount: l.billed_amount,
        })),
      };
      const created = await apiFetch("/claims/ingest/", { method: "POST", body });
      navigate(`/claims/${created.id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <h1>Ingest Claim</h1>

      <section className="card form-card" style={{ marginBottom: 20 }}>
        <h3>Upload EDI 837 File</h3>
        <p className="muted">
          Upload a standard X12 837P claims file. Every claim found in the file is
          ingested through the same pipeline as the manual form below.
        </p>
        <form onSubmit={handleEdiUpload} className="edi-upload-row">
          <input
            type="file"
            accept=".837,.txt,.edi"
            onChange={(e) => setEdiFile(e.target.files[0])}
          />
          <button type="submit" disabled={ediBusy || !ediFile}>
            {ediBusy ? "Uploading..." : "Upload & Ingest"}
          </button>
        </form>
        {ediError && <div className="error-text" style={{ marginTop: 10 }}>{ediError}</div>}
        {ediResults && (
          <ul className="simple-list" style={{ marginTop: 12 }}>
            {ediResults.map((r, i) => (
              <li key={i}>
                <span>{r.claim_number || "(unknown)"}</span>
                <span className={r.success ? "edi-ok" : "edi-fail"}>
                  {r.success ? `Ingested (id ${r.claim_id})` : `Failed: ${JSON.stringify(r.errors)}`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <h2>Or Enter Manually</h2>
      <form onSubmit={handleSubmit}>
        <div className="detail-grid">
          <section className="card form-card">
            <h3>Claim</h3>
            <label>Claim Number
              <input required value={claim.claim_number}
                onChange={(e) => setClaim({ ...claim, claim_number: e.target.value })} />
            </label>
            <label>Claim Type
              <input value={claim.claim_type}
                onChange={(e) => setClaim({ ...claim, claim_type: e.target.value })} />
            </label>
            <label>Authorization Number
              <input value={claim.authorization_number}
                onChange={(e) => setClaim({ ...claim, authorization_number: e.target.value })} />
            </label>
            <label>Date of Service
              <input type="date" required value={claim.date_of_service}
                onChange={(e) => setClaim({ ...claim, date_of_service: e.target.value })} />
            </label>
          </section>

          <section className="card form-card">
            <h3>Provider</h3>
            <label>Provider ID
              <input required value={provider.provider_id}
                onChange={(e) => setProvider({ ...provider, provider_id: e.target.value })} />
            </label>
            <label>Provider Name
              <input required value={provider.name}
                onChange={(e) => setProvider({ ...provider, name: e.target.value })} />
            </label>
            <label className="checkbox-label">
              <input type="checkbox" checked={provider.is_active}
                onChange={(e) => setProvider({ ...provider, is_active: e.target.checked })} />
              Provider is active
            </label>
          </section>

          <section className="card form-card">
            <h3>Member</h3>
            <label>Member ID
              <input required value={member.member_id}
                onChange={(e) => setMember({ ...member, member_id: e.target.value })} />
            </label>
            <label>Member Name
              <input required value={member.name}
                onChange={(e) => setMember({ ...member, name: e.target.value })} />
            </label>
            <label>Membership Status
              <select value={member.membership_status}
                onChange={(e) => setMember({ ...member, membership_status: e.target.value })}>
                <option value="ACTIVE">ACTIVE</option>
                <option value="INACTIVE">INACTIVE</option>
                <option value="TERMED">TERMED</option>
              </select>
            </label>
            <label>Membership Effective Date
              <input type="date" value={member.membership_effective_date}
                onChange={(e) => setMember({ ...member, membership_effective_date: e.target.value })} />
            </label>
          </section>

          <section className="card form-card">
            <h3>Service Lines</h3>
            {lines.map((l, i) => (
              <div key={i} className="line-row">
                <input placeholder="CPT" required value={l.cpt_code}
                  onChange={(e) => updateLine(i, "cpt_code", e.target.value)} />
                <input placeholder="Description" value={l.description}
                  onChange={(e) => updateLine(i, "description", e.target.value)} />
                <input type="number" min="1" placeholder="Units" value={l.units}
                  onChange={(e) => updateLine(i, "units", e.target.value)} />
                <input type="number" step="0.01" placeholder="Billed" required value={l.billed_amount}
                  onChange={(e) => updateLine(i, "billed_amount", e.target.value)} />
                {lines.length > 1 && (
                  <button type="button" className="link-button"
                    onClick={() => setLines(lines.filter((_, idx) => idx !== i))}>Remove</button>
                )}
              </div>
            ))}
            <button type="button" className="link-button" onClick={() => setLines([...lines, { ...emptyLine }])}>
              + Add service line
            </button>
            <p><strong>Total billed:</strong> {total.toFixed(2)}</p>
          </section>
        </div>

        {error && <div className="error-text" style={{ marginTop: 12 }}>{error}</div>}
        <div className="button-row" style={{ marginTop: 16 }}>
          <button type="submit" disabled={busy}>{busy ? "Submitting..." : "Ingest Claim"}</button>
        </div>
      </form>
    </div>
  );
}