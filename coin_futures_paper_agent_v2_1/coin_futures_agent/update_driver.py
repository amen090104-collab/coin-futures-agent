"""Stable stdlib dispatcher, kept after code rollback. No moving branch or network."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=('update', 'run', 'rollback', 'check', 'diagnose'))
    p.add_argument('--root', type=Path, required=True)
    args = p.parse_args(); root = args.root.resolve(); state = root/'.agent-updater'
    try:
        pointer = json.loads((state/'updater.json').read_text(encoding='utf-8'))
        sha = pointer['sha']
        if not re.fullmatch('[0-9a-f]{40}', sha): raise ValueError
        code = state/'releases'/sha/'code'
        proof = json.loads((code.parent/'SOURCE_CHECKSUMS.json').read_text(encoding='utf-8'))
        if proof.get('sha') != sha or not proof.get('files'): raise ValueError
        for relative, expected in proof['files'].items():
            path = code/relative
            if code.resolve() not in path.resolve().parents or path.is_symlink(): raise ValueError
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected: raise ValueError
        # root venv/py launches this driver; updater itself is stdlib. Selected
        # Agent version/venv stays independent and is verified again before Run.
        return subprocess.call([sys.executable, str(code/'remote_update.py'), args.action, '--root', str(root)],
                               cwd=root, env=dict(os.environ, PYTHONUTF8='1'))
    except (OSError, ValueError, KeyError, TypeError):
        print('UPDATE_BLOCKED_UPDATER_IDENTITY_OR_CHECKSUM'); return 1


if __name__ == '__main__': raise SystemExit(main())
