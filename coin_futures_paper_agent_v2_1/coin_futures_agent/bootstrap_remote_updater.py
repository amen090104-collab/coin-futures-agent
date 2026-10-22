"""One-time pinned Git bootstrap from installed fd829fc9. No manual ZIP or main pull."""
import argparse
import io
from pathlib import Path
import re
import subprocess
import sys
import zipfile

APP='coin_futures_paper_agent_v2_1/coin_futures_agent'


def git(root,*args):
    p=subprocess.run(['git',*args],cwd=root,capture_output=True,timeout=120)
    if p.returncode: raise ValueError('BOOTSTRAP_GIT_FAILED')
    return p.stdout


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True,type=Path);p.add_argument('--expected-sha',required=True)
    a=p.parse_args();root=a.root.resolve();sha=a.expected_sha
    try:
        if not re.fullmatch('[0-9a-f]{40}',sha): raise ValueError('BOOTSTRAP_FULL_SHA_REQUIRED')
        # Verify the fetched bootstrap bytes themselves, not a moving branch.
        git(root,'fetch','--no-tags','origin',sha)
        if git(root,'rev-parse','FETCH_HEAD').decode().strip()!=sha: raise ValueError('BOOTSTRAP_SHA_MISMATCH')
        if Path(__file__).read_bytes()!=git(root,'cat-file','blob',sha+':'+APP+'/bootstrap_remote_updater.py'):
            raise ValueError('BOOTSTRAP_CODE_CHECKSUM_FAILED')
        repository=git(root,'rev-parse','--show-toplevel').decode('utf-8').strip()
        archive=git(root,'-C',repository,'archive','--format=zip',sha+':'+APP)
        code=root/'.agent-updater/bootstrap'/sha/'code';code.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            for member in z.infolist():
                target=code/member.filename
                if code.resolve() not in target.resolve().parents or (member.external_attr>>16)&0o170000==0o120000:
                    raise ValueError('BOOTSTRAP_SOURCE_PATH_REJECTED')
            z.extractall(code)
        sys.path.insert(0,str(code))
        from v5_package import materialize
        from remote_update import RemoteUpdater
        package=code.parent/'package'
        materialize(package,sha,lambda name:(code/name).read_bytes())
        u=RemoteUpdater(root,package_root=package)
        result=u.update()  # approval, CI, checksum, backup, atomic activation.
        print(result)
        return 0 if result in {'V5_UPDATED_START_RUN_BAT','NO_NEW_VERSION'} else 2
    except Exception as exc:
        message=str(exc)
        print(message if re.fullmatch('[A-Z0-9_]{1,150}',message) else 'BOOTSTRAP_BLOCKED_NO_USER_DATA_CHANGED')
        return 1


if __name__=='__main__': raise SystemExit(main())
