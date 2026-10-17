"""Attrition risk model (pure Python — no Frappe / ML dependency).

A small, deterministic, interpretable scoring model. It maps normalised
employee features onto a (0, 1) attrition-risk score using a logistic
function, and returns per-feature contributions so the score is auditable.

The model is deliberately dependency-free so it runs identically inside the
Frappe scheduler, in unit tests, and on a real Docker host.
"""
from __future__ import annotations

import math
from typing import Optional

DEFAULT_WEIGHTS = {
    "attendance": 1.1,
    "unscheduled_leave": 1.3,
    "tenure": 0.8,
    "performance": 0.9,
    "hike": 0.7,
}
DEFAULT_BIAS = -0.4
LEVEL_BANDS = (("low", 0.00, 0.33), ("medium", 0.33, 0.66), ("high", 0.66, 1.01))


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def sigmoid(z: float) -> float:
    if z >= 0:
        z = -z
        return 1.0 / (1.0 + math.exp(z))
    return math.exp(z) / (1.0 + math.exp(z))


def risk_level(score: float) -> str:
    for name, low, high in LEVEL_BANDS:
        if low <= score < high:
            return name
    return "low"


def risk_score(
    features: dict,
    weights: Optional[dict] = None,
    bias: Optional[float] = None,
) -> dict:
    """Compute an attrition-risk score from normalised features.

    Expected features (all treated as optional, sensible defaults):
      attendance_rate         : 0..1  fraction of days attended (higher = better)
      unscheduled_leave_ratio : 0..1  recent unscheduled leave relative to prior
      tenure_months           : int   months since date of joining
      performance             : 0..1  normalised appraisal score
      salary_hike_pct         : float percentage of latest salary hike

    Returns a dict: {score, risk_level, contributions, features}.
    ``contributions`` names each feature's signed contribution before the
    sigmoid so the score can be explained to managers.
    """
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update({k: float(v) for k, v in weights.items() if v is not None})
    b = float(bias) if bias is not None else DEFAULT_BIAS

    attendance_rate = _clamp01(features.get("attendance_rate", 0.95))
    unscheduled_leave_ratio = _clamp01(features.get("unscheduled_leave_ratio", 0.0))
    tenure_months = max(0.0, float(features.get("tenure_months", 0.0) or 0.0))
    performance = _clamp01(features.get("performance", 0.6))
    hike_pct = max(0.0, float(features.get("salary_hike_pct", 0.0) or 0.0))

    c_attendance = w["attendance"] * (1.0 - attendance_rate)
    c_leave = w["unscheduled_leave"] * unscheduled_leave_ratio
    c_tenure = -w["tenure"] * (1.0 - math.exp(-tenure_months / 36.0))
    c_performance = w["performance"] * (1.0 - performance)
    c_hike = -w["hike"] * min(hike_pct / 10.0, 1.0)

    z = b + c_attendance + c_leave + c_tenure + c_performance + c_hike
    score = sigmoid(z)

    contributions = {
        "attendance": round(c_attendance, 4),
        "unscheduled_leave": round(c_leave, 4),
        "tenure": round(c_tenure, 4),
        "performance": round(c_performance, 4),
        "hike": round(c_hike, 4),
        "bias": round(b, 4),
    }
    used_features = {
        "attendance_rate": round(attendance_rate, 4),
        "unscheduled_leave_ratio": round(unscheduled_leave_ratio, 4),
        "tenure_months": round(tenure_months, 2),
        "performance": round(performance, 4),
        "salary_hike_pct": round(hike_pct, 2),
    }
    return {
        "score": round(score, 4),
        "risk_level": risk_level(score),
        "logit": round(z, 4),
        "contributions": contributions,
        "features": used_features,
    }


def calibrate_threshold(weights: Optional[dict] = None, bias: Optional[float] = None, rate: float = 0.5) -> float:
    """Find the logit offset (bias) that drives ~``rate`` of a synthetic cohort to high risk.

    Useful for tuning the model to a company's observed turnover without
    refitting: caller passes a bias and we return the resulting high-risk
    proportion over a synthetic feature grid.
    """
    grid = []
    for attendance_rate in (0.92, 0.98, 1.0):
        for unscheduled_leave_ratio in (0.0, 0.4, 0.9):
            for tenure_months in (3, 12, 36, 96):
                for performance in (0.5, 0.8, 1.0):
                    grid.append(
                        {
                            "attendance_rate": attendance_rate,
                            "unscheduled_leave_ratio": unscheduled_leave_ratio,
                            "tenure_months": tenure_months,
                            "performance": performance,
                            "salary_hike_pct": 4.0,
                        }
                    )
    high = sum(1 for f in grid if risk_score(f, weights=weights, bias=bias)["risk_level"] == "high")
    return round(high / len(grid), 4) if grid else 0.0