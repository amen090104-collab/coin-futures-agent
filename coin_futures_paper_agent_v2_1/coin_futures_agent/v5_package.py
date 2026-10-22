"""Code-only V5 package format shared by builder and stdlib updater."""
import hashlib
import json
from pathlib import Path
import re

BASE_SHA = '534011468670993e656b898d1ed049ebcfab8997'
APP_SUBDIR = 'coin_futures_paper_agent_v2_1/coin_futures_agent'
INFO = '.v5-update/BUILD_INFO.json'
SOURCES = {'update.bat':'update.bat','HUONG_DAN_CAP_NHAT_V5.txt':'HUONG_DAN_CAP_NHAT_V5.txt',
           **{'.v5-update/'+name:name for name in ('v5_update.py','v5_package.py','local_update.py',
                                                 'local_agent.py','safe_preupdate_backup.py')}}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def materialize(destination, sha, read_source):
    destination=Path(destination)
    if not re.fullmatch('[0-9a-f]{40}',sha):
        raise ValueError('V5_EXPECTED_FULL_SHA')
    manifest={'format':1,'version':'5.0.0','source_sha':sha,'v2_base_sha':BASE_SHA,
              'purpose':'PINNED_CODE_PACKAGE_MANUAL_INSTALL_OR_APPROVED_AUTOUPDATE','files':{},'source_paths':SOURCES}
    # Keep the 5.0 helper-envelope protocol compatible with already installed
    # fd829fc9 helpers. Agent version is independently verified against Git code.
    try:
        source_version = read_source('app/version.py').decode('utf-8')
        match = re.search(r'^VERSION\s*=\s*["\x27](5\.[0-9]+\.[0-9]+)', source_version, re.M)
        if match: manifest['agent_version']=match[1]
    except Exception:
        pass  # Minimal legacy helper-only fixtures have no application source.
    for relative,source in SOURCES.items():
        data=read_source(source)
        target=destination/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(data)
        manifest['files'][relative]=sha256(data)
    (destination/INFO).write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    verify_folder(destination)
    return manifest


def verify_folder(root):
    root=Path(root).resolve()
    if (root/'.v5-update').is_symlink() or (root/INFO).is_symlink():
        raise ValueError('UNSAFE_V5_PACKAGE_MANIFEST_PATH')
    manifest=json.loads((root/INFO).read_text(encoding='utf-8'))
    if (manifest.get('format')!=1 or manifest.get('version')!='5.0.0'
            or manifest.get('v2_base_sha')!=BASE_SHA or not re.fullmatch('[0-9a-f]{40}',manifest.get('source_sha',''))
            or manifest.get('source_paths')!=SOURCES or set(manifest.get('files',{}))!=set(SOURCES)):
        raise ValueError('INVALID_V5_PACKAGE_MANIFEST')
    for relative,checksum in manifest['files'].items():
        path=root/relative
        if (path.is_symlink() or any(p.is_symlink() for p in path.parents if p!=root and root in p.parents)
                or root not in path.resolve().parents or sha256(path.read_bytes())!=checksum):
            raise ValueError('V5_PACKAGE_CHECKSUM_OR_PATH_FAILED')
    return manifest


def verify_git(manifest, git):
    for relative,source in SOURCES.items():
        raw=git('cat-file','blob',manifest['source_sha']+':'+APP_SUBDIR+'/'+source,binary=True)
        if sha256(raw)!=manifest['files'][relative]:
            raise ValueError('V5_PACKAGE_DIFFERS_FROM_REVIEWED_GIT_BLOB')
