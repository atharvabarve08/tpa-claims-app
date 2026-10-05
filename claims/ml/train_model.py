"""
Trains the claim risk-scoring model on training_data.csv (see
generate_training_data.py) and saves TWO files:

  - risk_model.joblib          the model predict.py actually scores with.
                                Class-balanced + probability-calibrated (see below).
  - risk_model_explain.joblib  a plain, uncalibrated pipeline with the SAME
                                architecture, used only to generate the
                                plain-English "reasons" on the risk badge.
                                Calibration wraps the model in a way that makes
                                pulling out clean feature-coefficient reasons
                                awkward, so a second, simpler model trained on
                                the exact same data handles explanations while
                                the calibrated one handles the actual number.

Run: python train_model.py
Produces: risk_model.joblib, risk_model_explain.joblib

WHY class_weight="balanced": the original model only caught ~50% of real
problem claims (recall), because the training data is ~73% clean / 27%
problem, and an unweighted model can look "accurate" by mostly predicting
the majority class. Balancing re-weights the loss function so mistakes on
the minority (problem) class count more — the trade-off is more false
alarms on clean claims, which is normal and usually the right trade for a
"flag for review" use case: missing a real problem is more costly than an
extra review that turns out fine.

WHY calibration (CalibratedClassifierCV): a raw classifier's predict_proba
output isn't guaranteed to mean what it sounds like — a claim scored "70%"
isn't necessarily actually a problem 70% of the time. Calibration (via
5-fold cross-validation here) adjusts the output so the predicted
probabilities better match true observed frequencies. Brier score in the
evaluation output measures this directly (lower = better calibrated).

RETRAINING ON REAL DATA (do this once you have volume):
Replace generate_training_data.py's synthetic generation with a real query
of Claim + StatusHistory outcomes — see the note there. FEATURES below
should stay the same shape either way, so predict.py doesn't need to change.
"""

import joblib
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, classification_report, brier_score_loss

FEATURES = [
    "has_auth_number",
    "provider_active",
    "member_active",
    "provider_historical_denial_rate",
    "claim_amount",
    "num_service_lines",
    "days_from_membership_start",
]
TARGET = "outcome_problem"
MODEL_PATH = "risk_model.joblib"
EXPLAIN_MODEL_PATH = "risk_model_explain.joblib"


def build_pipeline():
    return Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=1000, class_weight="balanced")),
    ])


def main():
    df = pd.read_csv("training_data.csv")
    X = df[FEATURES]
    y = df[TARGET]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    # --- Explain model: plain, balanced, uncalibrated — used for feature-weight reasons ---
    explain_model = build_pipeline()
    explain_model.fit(X_train, y_train)

    print("=== Balanced (uncalibrated) — for comparison ===")
    y_pred = explain_model.predict(X_test)
    y_proba = explain_model.predict_proba(X_test)[:, 1]
    print(f"ROC AUC: {roc_auc_score(y_test, y_proba):.3f}")
    print(classification_report(y_test, y_pred, target_names=["clean", "problem"]))

    # --- Actual scoring model: same architecture, wrapped in calibration ---
    calibrated_model = CalibratedClassifierCV(build_pipeline(), method="sigmoid", cv=5)
    calibrated_model.fit(X_train, y_train)

    y_pred_cal = calibrated_model.predict(X_test)
    y_proba_cal = calibrated_model.predict_proba(X_test)[:, 1]

    print("\n=== Calibrated + balanced (this is what predict.py actually uses) ===")
    print(f"ROC AUC: {roc_auc_score(y_test, y_proba_cal):.3f}")
    print(f"Brier score (lower = better-calibrated probabilities): {brier_score_loss(y_test, y_proba_cal):.3f}")
    print(classification_report(y_test, y_pred_cal, target_names=["clean", "problem"]))

    coefs = explain_model.named_steps["clf"].coef_[0]
    print("=== Feature weights (standardized, from the explain model) ===")
    for name, coef in sorted(zip(FEATURES, coefs), key=lambda t: -abs(t[1])):
        print(f"  {name:35s} {coef:+.3f}")

    joblib.dump(calibrated_model, MODEL_PATH)
    joblib.dump(explain_model, EXPLAIN_MODEL_PATH)
    print(f"\nSaved scoring model to {MODEL_PATH}")
    print(f"Saved explain model to {EXPLAIN_MODEL_PATH}")


if __name__ == "__main__":
    main()