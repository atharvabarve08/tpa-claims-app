"""
Generates synthetic claim data to train the denial/hold risk model.

WHY SYNTHETIC: a real ML model needs hundreds+ of historical examples to learn
real patterns. This project has a handful of test claims — nowhere near enough.
So we simulate a population of claims with realistic, human-designed patterns
(missing auth numbers, inactive providers, "bad" provider tiers, high amounts
all correlate with a claim having problems), and train on that instead.

THIS IS A KNOWN LIMITATION, STATED HONESTLY: this model demonstrates the
*mechanism* (feature engineering, training, scoring, serving) end to end, but
its learned probabilities reflect the rules coded below, not real-world claims
behavior. Once real historical StatusHistory data accumulates, retrain
train_model.py on that instead — see the note at the bottom of train_model.py.

Run: python generate_training_data.py
Produces: training_data.csv (next to this script)
"""

import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)
N_SAMPLES = 2000
N_PROVIDERS = 40


def sigmoid(x):
    return 1 / (1 + np.exp(-x))


def generate():
    # Give each synthetic provider a fixed "quality tier" — this is what
    # provider_historical_denial_rate represents at inference time (computed
    # from real StatusHistory once the app has real data; here, simulated).
    provider_quality = RNG.beta(2, 6, size=N_PROVIDERS)  # skewed toward "good" providers
    provider_ids = RNG.integers(0, N_PROVIDERS, size=N_SAMPLES)
    provider_denial_rate = provider_quality[provider_ids]

    has_auth_number = RNG.choice([0, 1], size=N_SAMPLES, p=[0.15, 0.85])
    provider_active = RNG.choice([0, 1], size=N_SAMPLES, p=[0.05, 0.95])
    member_active = RNG.choice([0, 1], size=N_SAMPLES, p=[0.08, 0.92])

    claim_amount = RNG.lognormal(mean=6.0, sigma=0.9, size=N_SAMPLES)  # skewed, mostly small-mid, some large
    num_service_lines = RNG.integers(1, 6, size=N_SAMPLES)

    # Days between membership start and service date — negative means service
    # happened before coverage started (a real validation failure in the app).
    days_from_membership_start = RNG.integers(-60, 800, size=N_SAMPLES)

    # --- Simulated "true" risk function (this is the ground truth we're teaching the model to recover) ---
    logit = (
        -2.0
        + 3.0 * (1 - has_auth_number)
        + 2.5 * (1 - provider_active)
        + 1.8 * (1 - member_active)
        + 2.0 * provider_denial_rate
        + 0.8 * (days_from_membership_start < 0).astype(float)
        + 0.4 * (np.log1p(claim_amount) - 6.0)  # larger claims slightly riskier
        - 0.15 * num_service_lines            # more service lines = slightly more "normal", lower risk
    )
    prob_problem = sigmoid(logit)
    outcome_problem = RNG.binomial(1, prob_problem)  # 1 = denied/held, 0 = clean approval

    df = pd.DataFrame({
        "has_auth_number": has_auth_number,
        "provider_active": provider_active,
        "member_active": member_active,
        "provider_historical_denial_rate": provider_denial_rate,
        "claim_amount": claim_amount,
        "num_service_lines": num_service_lines,
        "days_from_membership_start": days_from_membership_start,
        "outcome_problem": outcome_problem,
    })
    return df


if __name__ == "__main__":
    df = generate()
    df.to_csv("training_data.csv", index=False)
    print(f"Wrote {len(df)} synthetic rows to training_data.csv")
    print(f"Problem rate in synthetic data: {df['outcome_problem'].mean():.2%}")