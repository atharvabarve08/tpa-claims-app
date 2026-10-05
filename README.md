# TPA Claims Management Application

A claims management platform built for the **Collabrios Health Platform — TPA Modernization** initiative. It covers the full claims lifecycle — ingestion, validation, pricing, approval, payment, and analytics — with background workers that automate each step and stop a claim at a hold the moment any check fails.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django + Django REST Framework |
| Database | PostgreSQL |
| Background workers | Celery (worker + beat) |
| Message broker | Redis-compatible (Memurai on Windows) |
| Frontend | React (Vite) |
| Predictive analysis | scikit-learn (logistic regression) |

## The Six Stages

1. **Data Ingestion** — manual entry, a JSON API endpoint, or an EDI 837P file upload. Every attempt is logged (success or failure) in `IngestionLog`.
2. **Validation** — a Celery worker checks member eligibility, provider status, duplicate claims, authorization number, and service lines. Any failure stops the claim at `VALIDATION_HOLD` with the reason recorded.
3. **Pricing** — calculates allowed/approved amounts per service line, then submits the claim for approval.
4. **Verification (Approval)** — a `CLAIMS_APPROVER` approves, denies, or pends the claim via the API/UI.
5. **Payment** — payment approval, scheduling (ACH or check), and automatic execution on the scheduled date via a Celery beat task, which generates an Explanation of Payment (EOP).
6. **Analytics & Reporting** — a dashboard of claim counts, payment volume, turnaround time, and provider/member breakdowns, filterable by date, status, provider, and member.

Every status change is recorded in `StatusHistory`, giving a full audit trail and feeding the analytics in Stage 6.

## Roles

| Role | Can do |
|---|---|
| `CLAIMS_SUBMITTER` | Ingest claims, submit for payment approval, schedule payments |
| `CLAIMS_APPROVER` | Approve/deny/pend claims and payments |
| `TPA_MANAGER` | Everything above, plus analytics access |

Enforced via token authentication and per-view DRF permission classes.

## Additional Features

- **Predictive risk scoring** — a scikit-learn model estimates the probability a new claim is denied or held, shown as a badge on the claim detail page. **Currently trained on synthetic data** (see `claims/ml/README` notes in `generate_training_data.py`) — retrain on real historical claims once sufficient volume exists.
- **EDI 837P ingestion** — uploads a standard X12 837 Professional claims file and ingests every claim it contains through the same pipeline as manual entry. Does not yet cover 837I (institutional), multiple diagnosis codes, or coordination of benefits.
- **Hold recovery** — a stuck claim can be fixed via the Edit Claim form (for claim-level issues like a missing auth number) or re-checked on demand via Retry Now (for external fixes, like reactivating a provider), instead of being permanently stuck.

## Project Structure

```
tpa_claims_app/
├── manage.py
├── tpa_claims_app/          # Django project settings, urls, celery.py
├── claims/                  # Main app
│   ├── models.py            # Claim, ServiceLine, Provider, Member, Payment, StatusHistory, UserProfile
│   ├── transitions.py       # Central status-transition rules + audit logging
│   ├── tasks.py             # Celery tasks: ingest, validate, price, execute payment, retry holds
│   ├── views.py             # API views (ingestion, approval, payment, risk score, edit, retry)
│   ├── serializers.py
│   ├── permissions.py       # Role-based permission classes
│   ├── analytics.py         # Stage 6 dashboard endpoint
│   ├── edi/
│   │   └── edi837_parser.py # X12 837P parser
│   └── ml/
│       ├── generate_training_data.py
│       ├── train_model.py
│       ├── predict.py
│       └── inspect_model.py
└── frontend/                 # React app (Vite)
    └── src/
        ├── api.js
        ├── App.jsx
        └── pages/            # Login, ClaimsList, ClaimDetail, IngestClaim, Dashboard
```

## Setup

### Backend

```bash
cd tpa_claims_app
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt

# Create the database (Postgres must be running)
createdb -U postgres tpa_claims

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

### Background workers

Needs a running Redis-compatible broker (Memurai on Windows) in addition to Django:

```bash
celery -A tpa_claims_app worker -l info --pool=solo   # Windows needs --pool=solo
celery -A tpa_claims_app beat -l info
```

### Predictive model

```bash
cd claims/ml
python generate_training_data.py
python train_model.py
```

Produces `risk_model.joblib` and `risk_model_explain.joblib`, used by `predict.py`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Runs at `http://localhost:5173`, talking to the Django API at `http://127.0.0.1:8000`.

## Known Limitations

- The predictive risk model is trained on **synthetic data**, not real claims — it demonstrates the full pipeline (feature engineering → training → serving → UI) but its probabilities shouldn't be trusted for real decisions yet.
- EDI ingestion supports **837P (Professional) only** — not 837I (Institutional) or coordination-of-benefits segments.
- No HIPAA-specific compliance hardening has been applied; this is a demonstration/internship project, not a production-certified system.