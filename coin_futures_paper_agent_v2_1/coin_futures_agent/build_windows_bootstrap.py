"""Build a reviewable code-only installer artifact; never package DB/.env/reports."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import zipfile
import re

FILES = ('CAI_DAT_VAO_BAN_V2.bat','bootstrap_windows.py','local_agent.py','local_update.py',
         'safe_preupdate_backup.py','approved_release.json','WINDOWS_UPDATE_V3.md')


APP_SUBDIR = 'coin_futures_paper_agent_v2_1/coin_futures_agent'


def git_bytes(root, *args):
    return subprocess.run(['git',*args],cwd=root,capture_output=True,check=True).stdout


def build(output, *, expected_sha=None, root=None):
    root=Path(root or Path(__file__).resolve().parent)
    sha=git_bytes(root,'rev-parse','HEAD').decode().strip()
    expected_sha=expected_sha or sha
    if not re.fullmatch('[0-9a-f]{40}',expected_sha) or sha != expected_sha:
        raise ValueError('ARTIFACT_SHA_MUST_MATCH_REVIEWED_PIN')
    manifest={'code_sha':sha,'purpose':'REVIEW_ARTIFACT_NOT_APPROVED_RELEASE','files':{}}
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            # Use immutable Git blobs: CRLF checkout conversion or a modified workspace
            # cannot silently change the bytes attributed to the reviewed commit.
            data=git_bytes(root,'cat-file','blob',sha+':'+APP_SUBDIR+'/'+name)
            archive.writestr(name,data)
            manifest['files'][name]=hashlib.sha256(data).hexdigest()
        archive.writestr('BUILD_INFO.json',json.dumps(manifest,indent=2))
    verify(output,expected_sha=expected_sha,root=root)
    return manifest


def verify(output, *, expected_sha, root=None):
    root=Path(root or Path(__file__).resolve().parent)
    if not re.fullmatch('[0-9a-f]{40}', expected_sha):
        raise ValueError('ARTIFACT_REVIEWED_PIN_MUST_BE_FULL_SHA')
    with zipfile.ZipFile(output) as archive:
        if set(archive.namelist()) != {*FILES,'BUILD_INFO.json'} or len(archive.namelist()) != len(FILES)+1:
            raise ValueError('UNEXPECTED_BOOTSTRAP_FILES')
        manifest=json.loads(archive.read('BUILD_INFO.json'))
        if manifest['code_sha'] != expected_sha or set(manifest['files']) != set(FILES):
            raise ValueError('ARTIFACT_REVIEWED_PIN_MISMATCH')
        for name in FILES:
            data=archive.read(name)
            if (hashlib.sha256(data).hexdigest() != manifest['files'][name]
                    or data != git_bytes(root,'cat-file','blob',expected_sha+':'+APP_SUBDIR+'/'+name)):
                raise ValueError('ARTIFACT_DIFFERS_FROM_PINNED_GIT_BLOB')
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('output',type=Path)
    parser.add_argument('--expected-sha',required=True)
    parser.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    if args.verify:
        verify(args.output,expected_sha=args.expected_sha)
    else:
        build(args.output,expected_sha=args.expected_sha)
