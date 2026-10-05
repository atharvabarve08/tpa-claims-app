"""
Scores a claim's risk of being denied or held, using the model trained by
train_model.py (risk_model.joblib in this folder).

Two layers, on purpose:
  - build_features(claim)  needs the database (Django ORM) to compute features.
  - score_features(dict)   is pure — takes the feature dict, returns the score.
Keeping them separate makes the scoring logic testable without Django.

The feature names and order MUST match FEATURES in train_model.py.
"""

from pathlib import Path

import joblib
import pandas as pd

MODEL_PATH = Path(__file__).resolve().parent / "risk_model.joblib"
EXPLAIN_MODEL_PATH = Path(__file__).resolve().parent / "risk_model_explain.joblib"

FEATURES = [
    "has_auth_number",
    "provider_active",
    "member_active",
    "provider_historical_denial_rate",
    "claim_amount",
    "num_service_lines",
    "days_from_membership_start",
]

# A provider with little history shouldn't get an extreme rate from 1-2 claims,
# so we blend their real rate with a prior (the average in the training data).
PRIOR_PROVIDER_RATE = 0.25
PRIOR_WEIGHT = 5  # acts like "5 imaginary past claims at the prior rate"

# Used when a member has no membership_effective_date on file.
NEUTRAL_DAYS_FROM_MEMBERSHIP_START = 365

_model = None
_explain_model = None


class ModelNotAvailable(Exception):
    """Raised when a model file is missing or can't be loaded."""


def _load(path, label):
    if not path.exists():
        raise ModelNotAvailable(f"{label} not found. Run train_model.py inside claims/ml first.")
    try:
        return joblib.load(path)
    except Exception as exc:  # e.g. scikit-learn version mismatch
        raise ModelNotAvailable(f"{label} could not be loaded ({exc}). Retrain it with train_model.py.")


def _load_model():
    global _model
    if _model is None:
        _model = _load(MODEL_PATH, "Risk model")
    return _model


def _load_explain_model():
    """
    The scoring model (_load_model) is calibration-wrapped, which makes pulling
    clean feature coefficients out awkward. This separate, uncalibrated model
    — same features, same training data — exists purely to generate the
    plain-English reasons; it never produces the probability shown to the user.
    """
    global _explain_model
    if _explain_model is None:
        _explain_model = _load(EXPLAIN_MODEL_PATH, "Risk explain model")
    return _explain_model


def provider_denial_rate(claim) -> float:
    """
    Smoothed share of this provider's OTHER claims that were denied or ever
    put on hold. Computed live from real Claim/StatusHistory rows, so the
    score gets more accurate as real data accumulates.
    """
    from django.db.models import Q

    from claims.models import Claim  # imported here to avoid import cycles at startup

    others = Claim.objects.filter(provider=claim.provider).exclude(pk=claim.pk)
    total = others.count()
    problems = (
        others.filter(
            Q(status_history__to_status="DENIED")
            | Q(status_history__to_status__endswith="_HOLD")
        )
        .distinct()
        .count()
    )
    return (problems + PRIOR_PROVIDER_RATE * PRIOR_WEIGHT) / (total + PRIOR_WEIGHT)


def build_features(claim) -> dict:
    if claim.member.membership_effective_date:
        days = (claim.date_of_service - claim.member.membership_effective_date).days
    else:
        days = NEUTRAL_DAYS_FROM_MEMBERSHIP_START

    return {
        "has_auth_number": 1 if claim.authorization_number else 0,
        "provider_active": 1 if claim.provider.is_active else 0,
        "member_active": 1 if claim.member.membership_status == "ACTIVE" else 0,
        "provider_historical_denial_rate": provider_denial_rate(claim),
        "claim_amount": float(claim.total_claim_amount),
        "num_service_lines": claim.service_lines.count(),
        "days_from_membership_start": days,
    }


# Plain-English explanation per feature. Each returns text only when that
# feature's raw value actually justifies the message, otherwise None.
_REASON_TEXT = {
    "has_auth_number": lambda f: None if f["has_auth_number"] else "No authorization number on the claim",
    "provider_active": lambda f: None if f["provider_active"] else "Provider is inactive",
    "member_active": lambda f: None if f["member_active"] else "Member is not active",
    "provider_historical_denial_rate": lambda f: (
        f"Provider has a {f['provider_historical_denial_rate']:.0%} historical denial/hold rate"
    ),
    "claim_amount": lambda f: f"Claim amount ({f['claim_amount']:,.2f}) is high compared to typical claims",
    "num_service_lines": lambda f: "Only one service line on the claim" if f["num_service_lines"] <= 1 else None,
    "days_from_membership_start": lambda f: (
        "Service date is before the member's coverage started"
        if f["days_from_membership_start"] < 0
        else None
    ),
}


def _level(probability: float) -> str:
    if probability < 0.25:
        return "LOW"
    if probability < 0.5:
        return "MEDIUM"
    return "HIGH"


def score_features(features: dict) -> dict:
    model = _load_model()
    explain_model = _load_explain_model()
    row = pd.DataFrame([[features[name] for name in FEATURES]], columns=FEATURES)

    # The probability shown to the user comes from the calibrated model —
    # the whole point of calibration is that this number should actually
    # mean what it says (a claim scored 70% should turn out bad ~70% of the time).
    probability = float(model.predict_proba(row)[0, 1])

    # Explain the score using the separate, uncalibrated explain model: each
    # feature's contribution to the log-odds is (standardized value x learned
    # weight). The biggest positive ones are what pushed this claim's risk up.
    scaler = explain_model.named_steps["scaler"]
    coefs = explain_model.named_steps["clf"].coef_[0]
    scaled = scaler.transform(row)[0]
    contributions = sorted(
        ((coefs[i] * scaled[i], FEATURES[i]) for i in range(len(FEATURES))),
        reverse=True,
    )

    level = _level(probability)

    # Only explain claims that actually look risky; a LOW score needs no excuses.
    reasons = []
    if level != "LOW":
        for contribution, name in contributions:
            if contribution < 0.15 or len(reasons) == 3:
                break
            text = _REASON_TEXT[name](features)
            if text:
                reasons.append(text)

    return {
        "probability": round(probability, 4),
        "level": level,
        "reasons": reasons,
    }


def score_claim(claim) -> dict:
    return score_features(build_features(claim))