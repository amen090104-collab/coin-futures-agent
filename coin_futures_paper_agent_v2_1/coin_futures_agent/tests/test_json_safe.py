import math

from app.analytics import _f
from app.json_safe import json_safe


def test_json_safe_replaces_nan_and_infinity_recursively():
    data = {
        "nan": float("nan"),
        "inf": float("inf"),
        "nested": [1.0, float("-inf"), {"x": float("nan")}],
    }
    out = json_safe(data)
    assert out == {
        "nan": None,
        "inf": None,
        "nested": [1.0, None, {"x": None}],
    }


def test_analytics_float_helper_rejects_non_finite_values():
    assert _f(float("nan")) == 0.0
    assert _f(float("inf")) == 0.0
    assert _f("-inf") == 0.0
    assert _f("12.5") == 12.5
