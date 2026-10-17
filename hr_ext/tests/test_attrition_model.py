"""Unit tests for the attrition risk model (pure, no Frappe/DB)."""
import math
import unittest

from hr_ext.analytics.model import DEFAULT_WEIGHTS, risk_level, risk_score, sigmoid


class TestAttritionModel(unittest.TestCase):
    def test_sigmoid_bounds(self):
        for z in (-100, -1, 0, 1, 100):
            self.assertTrue(0.0 <= sigmoid(z) <= 1.0)
        self.assertAlmostEqual(sigmoid(0), 0.5, places=6)
        self.assertAlmostEqual(sigmoid(1.0), 1.0 - sigmoid(-1.0), places=6)

    def test_low_risk_profile(self):
        result = risk_score(
            {
                "attendance_rate": 1.0,
                "unscheduled_leave_ratio": 0.0,
                "tenure_months": 96,
                "performance": 1.0,
                "salary_hike_pct": 4.0,
            }
        )
        self.assertLess(result["score"], 0.5)
        self.assertEqual(result["risk_level"], "low")

    def test_high_risk_profile(self):
        result = risk_score(
            {
                "attendance_rate": 0.7,
                "unscheduled_leave_ratio": 0.9,
                "tenure_months": 3,
                "performance": 0.4,
                "salary_hike_pct": 0.0,
            }
        )
        self.assertGreater(result["score"], 0.66)
        self.assertEqual(result["risk_level"], "high")

    def test_deterministic(self):
        features = {"attendance_rate": 0.8, "unscheduled_leave_ratio": 0.3, "tenure_months": 24, "performance": 0.6, "salary_hike_pct": 2.0}
        self.assertEqual(risk_score(features), risk_score(features))

    def test_input_clamping(self):
        result = risk_score({"attendance_rate": -5, "unscheduled_leave_ratio": 99, "tenure_months": -2, "performance": 7})
        self.assertLessEqual(result["features"]["attendance_rate"], 1.0)
        self.assertGreaterEqual(result["features"]["attendance_rate"], 0.0)
        self.assertEqual(result["risk_level"], risk_level(result["score"]))

    def test_contributions_reconstruct_logit(self):
        features = {"attendance_rate": 0.81, "unscheduled_leave_ratio": 0.32, "tenure_months": 24, "performance": 0.55, "salary_hike_pct": 2.5}
        result = risk_score(features)
        contrib = result["contributions"]
        self.assertAlmostEqual(sum(contrib.values()), result["logit"], places=3)
        self.assertAlmostEqual(sigmoid(result["logit"]), result["score"], delta=1.1e-4)  # score rounded to 4dp

    def test_weights_override_monotonic(self):
        base = {"attendance_rate": 0.8, "unscheduled_leave_ratio": 0.0, "tenure_months": 24, "performance": 0.7, "salary_hike_pct": 2.0}
        normal = risk_score(base)
        guard = risk_score(base, weights={**DEFAULT_WEIGHTS, "attendance": 5.0})
        self.assertGreater(guard["score"], normal["score"])

    def test_calibrate_threshold(self):
        prop = __import__("hr_ext.analytics.model", fromlist=["calibrate_threshold"]).calibrate_threshold(bias=1.5)
        self.assertTrue(0.0 < prop < 1.0)
        self.assertGreater(
            __import__("hr_ext.analytics.model", fromlist=["calibrate_threshold"]).calibrate_threshold(bias=5.0),
            prop,
        )


if __name__ == "__main__":
    unittest.main()