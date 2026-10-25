"""Catch JS syntax failures in the minimal dashboard on both CI platforms."""
import re
import shutil
import subprocess

import pytest
from app.dashboard_lean import DASHBOARD_HTML_LEAN


def test_lean_html_has_five_tabs_and_no_deprecated_chart_widgets():
    markup = DASHBOARD_HTML_LEAN
    assert len(re.findall(r'data-tab="[^"]+"', markup)) == 4
    for removed in ('coinChart', 'tradeChart', 'TradeCharts', 'replayStart',
                    'Exit Simulator', 'Trade path', '/coins/'):
        assert removed not in markup


def test_lean_embedded_javascript_parses(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is not installed outside CI")
    match = re.search(r"<script>(.*?)</script>", DASHBOARD_HTML_LEAN, re.S)
    assert match, "Minimal dashboard script missing"
    target = tmp_path / "minimal-dashboard.js"
    target.write_text(match.group(1), encoding="utf-8")
    result = subprocess.run([node, "--check", str(target)], capture_output=True,
                            text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr
