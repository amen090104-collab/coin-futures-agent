"""Prepare a source-pinned release manifest/one-time command. Publication is manual."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from local_update import command, APP_SUBDIR, UpdateError
from remote_release import GitHub, verify_review, source_digest, version


def bootstrap_command(sha, file_sha256):
    if not re.fullmatch('[0-9a-f]{40}',sha) or not re.fullmatch('[0-9a-f]{64}',file_sha256): raise ValueError('INVALID_BOOTSTRAP_PIN')
    # CMD once, using the existing installed venv. Bytes are captured directly
    # from Git; no PowerShell encoding conversion or unauthenticated curl pipe.
    code=("import hashlib,pathlib,subprocess,sys; s='"+sha+"'; "
        "subprocess.run(['git','fetch','--no-tags','origin',s],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
        "b=subprocess.check_output(['git','cat-file','blob',s+':"+APP_SUBDIR+"/bootstrap_remote_updater.py'],stderr=subprocess.DEVNULL); "
        "assert hashlib.sha256(b).hexdigest()=='"+file_sha256+"','BOOTSTRAP_CHECKSUM_FAILED'; "
        "p=pathlib.Path('.agent-updater/bootstrap-once.py'); p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b); "
        "sys.exit(subprocess.call([sys.executable,str(p),'--root','.','--expected-sha',s]))")
    return '".venv\\Scripts\\python.exe" -c "'+code+'"'


def build(root, *, sha, tag, review_url, reviewed=False):
    version(tag)
    if not re.fullmatch('[0-9a-f]{40}',sha): raise UpdateError('FULL_RELEASE_SHA_REQUIRED')
    root=Path(root)
    repo=command(['git','rev-parse','--show-toplevel'],cwd=root)
    raw=command(['git','-C',repo,'archive','--format=zip',sha+':'+APP_SUBDIR],cwd=root,binary=True)
    source=command(['git','cat-file','blob',sha+':'+APP_SUBDIR+'/app/version.py'],cwd=root)
    match=re.search(r'^VERSION\s*=\s*["\x27]([^"\x27]+)',source,re.M)
    if not match or 'v'+match[1]!=tag: raise UpdateError('RELEASE_VERSION_MUST_MATCH_SOURCE')
    pin={'sha':sha,'reviewed':reviewed,'review_url':review_url}
    if reviewed: verify_review(pin,GitHub(root).get)
    return {'manifest_version':2,'version':tag[1:],'approved_release':pin,
            'execution_mode':'PAPER_SHADOW_ONLY','source_tree_sha256':source_digest(raw),
            'model_profitability_verified':False,'installation':'git_source_archive_no_manual_zip',
            'qualification':'Software approval is separate from research model qualification.'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--sha',required=True);p.add_argument('--tag')
    p.add_argument('--review-url',required=True);p.add_argument('--verify-reviewed',action='store_true')
    p.add_argument('--output-dir',required=True,type=Path);a=p.parse_args();root=Path(__file__).resolve().parent
    if not a.tag:
        source=command(['git','cat-file','blob',a.sha+':'+APP_SUBDIR+'/app/version.py'],cwd=root)
        a.tag='v'+re.search(r'^VERSION\s*=\s*["\x27]([^"\x27]+)',source,re.M)[1]
    result=build(root,sha=a.sha,tag=a.tag,review_url=a.review_url,reviewed=a.verify_reviewed)
    a.output_dir.mkdir(parents=True,exist_ok=True)
    (a.output_dir/'release-manifest.json').write_text(json.dumps(result,indent=2)+'\n',encoding='ascii')
    raw=command(['git','cat-file','blob',a.sha+':'+APP_SUBDIR+'/bootstrap_remote_updater.py'],cwd=root,binary=True)
    (a.output_dir/'KICH_HOAT_UPDATER_MOT_LAN.txt').write_text(bootstrap_command(a.sha,hashlib.sha256(raw).hexdigest())+'\n',encoding='ascii')
    print('APPROVED_RELEASE_MANIFEST' if a.verify_reviewed else 'DRAFT_MANIFEST_NOT_AUTHORIZED_FOR_INSTALL')


if __name__=='__main__': main()
