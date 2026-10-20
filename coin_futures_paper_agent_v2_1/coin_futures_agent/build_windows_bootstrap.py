"""Build a reviewable code-only installer artifact; never package DB/.env/reports."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import zipfile

FILES = ('CAI_DAT_VAO_BAN_V2.bat','bootstrap_windows.py','local_agent.py','local_update.py',
         'safe_preupdate_backup.py','approved_release.json','WINDOWS_UPDATE_V3.md')


def build(output):
    root=Path(__file__).resolve().parent
    sha=subprocess.run(['git','rev-parse','HEAD'],cwd=root,capture_output=True,text=True,check=True).stdout.strip()
    manifest={'code_sha':sha,'purpose':'REVIEW_ARTIFACT_NOT_APPROVED_RELEASE','files':{}}
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            data=(root/name).read_bytes()
            archive.writestr(name,data)
            manifest['files'][name]=hashlib.sha256(data).hexdigest()
        archive.writestr('BUILD_INFO.json',json.dumps(manifest,indent=2))
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('output',type=Path)
    build(parser.parse_args().output)
