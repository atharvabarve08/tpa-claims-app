"""
Loads both model files and prints their learned internals in plain,
readable form — this is what's actually "inside" the .joblib files,
since the files themselves are binary and can't be opened directly.

Run: python inspect_model.py
"""

import joblib

FEATURES = [
    "has_auth_number",
    "provider_active",
    "member_active",
    "provider_historical_denial_rate",
    "claim_amount",
    "num_service_lines",
    "days_from_membership_start",
]


def inspect_explain_model():
    print("=" * 70)
    print("risk_model_explain.joblib — the interpretable model (for 'reasons')")
    print("=" * 70)

    model = joblib.load("risk_model_explain.joblib")
    print(f"Python type: {type(model)}")
    print(f"Pipeline steps: {list(model.named_steps.keys())}")

    scaler = model.named_steps["scaler"]
    print("\n--- StandardScaler: how each feature is scaled before scoring ---")
    for name, mean, scale in zip(FEATURES, scaler.mean_, scaler.scale_):
        print(f"  {name:35s} mean={mean:10.3f}  std={scale:10.3f}")

    clf = model.named_steps["clf"]
    print(f"\n--- LogisticRegression: intercept = {clf.intercept_[0]:+.3f} ---")
    print("(the baseline log-odds before any feature is considered)")
    print("\n--- Learned weight per feature (bigger magnitude = more influence) ---")
    for name, coef in sorted(zip(FEATURES, clf.coef_[0]), key=lambda t: -abs(t[1])):
        direction = "increases risk" if coef > 0 else "decreases risk"
        print(f"  {name:35s} {coef:+.3f}   ({direction})")


def inspect_scoring_model():
    print("\n" + "=" * 70)
    print("risk_model.joblib — the calibrated model actually used to score claims")
    print("=" * 70)

    model = joblib.load("risk_model.joblib")
    print(f"Python type: {type(model)}")
    print(f"Calibration method: {model.method}")
    print(f"Number of cross-validation folds used: {len(model.calibrated_classifiers_)}")
    print(
        "\nThis one wraps 5 separately-trained copies of the same pipeline "
        "(one per CV fold) plus a calibration curve on top. That structure "
        "is exactly why it's awkward to pull a single 'the model said X' "
        "coefficient out of it directly — which is why risk_model_explain.joblib "
        "exists as a separate, simpler model just for generating reasons."
    )


if __name__ == "__main__":
    inspect_explain_model()
    inspect_scoring_model()