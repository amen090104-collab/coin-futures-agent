from types import SimpleNamespace

from app.battle import _variant_geometry
from app.config import settings


def test_four_case_geometry(monkeypatch):
    monkeypatch.setattr(settings, "slippage_bps", 0.0)
    plan = SimpleNamespace(side="LONG", entry=100.0, stop_loss=98.0)

    side_a, entry_a, stop_a, tp_a = _variant_geometry(plan, "BASE_RR2")
    side_b, entry_b, stop_b, tp_b = _variant_geometry(plan, "BASE_RR1")
    side_c, entry_c, stop_c, tp_c = _variant_geometry(plan, "REVERSE_RR2")
    side_d, entry_d, stop_d, tp_d = _variant_geometry(plan, "REVERSE_RR1")

    assert (side_a, entry_a, stop_a, tp_a) == ("LONG", 100.0, 98.0, 104.0)
    assert (side_b, entry_b, stop_b, tp_b) == ("LONG", 100.0, 98.0, 102.0)
    assert (side_c, entry_c, stop_c, tp_c) == ("SHORT", 100.0, 102.0, 96.0)
    assert (side_d, entry_d, stop_d, tp_d) == ("SHORT", 100.0, 102.0, 98.0)


def test_reverse_short_source_becomes_long(monkeypatch):
    monkeypatch.setattr(settings, "slippage_bps", 0.0)
    plan = SimpleNamespace(side="SHORT", entry=100.0, stop_loss=103.0)
    side, entry, stop, tp = _variant_geometry(plan, "REVERSE_RR2")
    assert side == "LONG"
    assert entry == 100.0
    assert stop == 97.0
    assert tp == 106.0
