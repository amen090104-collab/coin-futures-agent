"""Identity of executing code, separate from research/model qualification."""
from pathlib import Path
import json
import os
import re
import subprocess

VERSION = "5.0.0"
APP_ROOT = Path(__file__).resolve().parents[1]


def version_info():
    sha = os.environ.get('AGENT_RELEASE_SHA', '')
    status = 'ACCEPTANCE_PENDING'
    try:
        build = json.loads((APP_ROOT/'.build-info.json').read_text(encoding='utf-8'))
        if (build.get('version') == VERSION and re.fullmatch('[0-9a-f]{40}', build.get('sha', ''))
                and build.get('approval') == 'REVIEWED_RELEASE'):
            sha, status = build['sha'], 'REVIEWED_RELEASE'
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    if not re.fullmatch('[0-9a-f]{40}', sha):
        try:
            result = subprocess.run(['git','rev-parse','HEAD'],cwd=APP_ROOT,capture_output=True,text=True,timeout=3)
            sha = result.stdout.strip() if result.returncode == 0 else ''
        except (OSError, subprocess.TimeoutExpired):
            sha = ''
    return {'version':VERSION,'name':'Trading Bot V5.0','sha':sha if re.fullmatch('[0-9a-f]{40}', sha) else None,
            'release_status':status,'execution_mode':'PAPER_SHADOW_ONLY','real_orders_enabled':False}
