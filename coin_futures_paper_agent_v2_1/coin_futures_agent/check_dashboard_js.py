"""Portable JS syntax check; no shell python -c quoting or Windows /tmp assumptions."""
from pathlib import Path
import re
import subprocess
import tempfile
from app.dashboard_v43 import DASHBOARD_HTML_V43


def main():
    match = re.search(r'<script>([\s\S]*?)</script>', DASHBOARD_HTML_V43)
    if not match:
        raise ValueError('Inline dashboard script missing')
    with tempfile.TemporaryDirectory() as directory:
        script = Path(directory)/'dashboard.js'
        script.write_text(match.group(1), encoding='utf-8')
        subprocess.run(['node', '--check', str(script)], check=True)


if __name__ == '__main__':
    main()
