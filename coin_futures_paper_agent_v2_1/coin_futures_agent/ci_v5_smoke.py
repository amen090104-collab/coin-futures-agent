"""Real public HTTP outside offline pytest. Regional denial is evidence, never synthetic success."""
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    out=Path('v5-ci-market')
    args=[sys.executable,'-m','app.v5_acceptance','--output-dir',str(out),'--reconstruct-limit','0']
    sha=os.environ.get('REVIEWED_CODE_SHA')
    if sha:args+=['--expected-sha',sha]
    result=subprocess.run(args,timeout=420)
    if result.returncode not in (0,2):return result.returncode
    evidence=json.loads((out/'acceptance.redacted.json').read_text(encoding='utf-8'))
    market=evidence['market'];kind='notice' if market['release_market_evidence'] else 'warning'
    print(f'::{kind} title=V5 public market smoke::status={market["status"]} verified={market["verified_windows"]}/{market["attempted_windows"]}; windows_user_copy=false; private READY=0; NOT release acceptance',flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
