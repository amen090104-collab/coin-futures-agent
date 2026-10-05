from __future__ import annotations

STRATEGIES = {
    "BASE_RR2": {
        "name": "CASE A - BASE 1:2",
        "short_name": "A",
        "rr": 2.0,
        "reverse": False,
        "description": "Chiến lược hiện tại: cùng hướng tín hiệu, TP = 2R.",
    },
    "BASE_RR1": {
        "name": "CASE B - BASE 1:1",
        "short_name": "B",
        "rr": 1.0,
        "reverse": False,
        "description": "Cùng Entry/SL với Case A nhưng TP = 1R.",
    },
    "REVERSE_RR2": {
        "name": "CASE C - REVERSE 1:2",
        "short_name": "C",
        "rr": 2.0,
        "reverse": True,
        "description": "Đảo ngược hướng của tín hiệu gốc, dùng TP = 2R.",
    },
}

STRATEGY_IDS = tuple(STRATEGIES.keys())
