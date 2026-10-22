import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

import pytest
from build_windows_bootstrap import build, verify, FILES, APP_SUBDIR

ROOT=Path(__file__).resolve().parents[1]


def head():
    return subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()


def test_artifact_matches_intended_pin_and_every_git_blob(tmp_path):
    target=tmp_path/'bootstrap.zip'
    manifest=build(target,expected_sha=head())
    assert manifest['code_sha']==head() and len(manifest['files'])==len(FILES)
    assert verify(target,expected_sha=head())==manifest


def test_synthetic_merge_or_wrong_pin_rejected_before_build(tmp_path):
    target=tmp_path/'must-not-exist.zip'
    with pytest.raises(ValueError,match='REVIEWED_PIN'):
        build(target,expected_sha='0'*40)
    assert not target.exists()


def test_tampered_content_even_with_updated_checksum_is_not_reviewed_code(tmp_path):
    original=tmp_path/'bootstrap.zip';altered=tmp_path/'tampered.zip'
    build(original,expected_sha=head())
    with zipfile.ZipFile(original) as src, zipfile.ZipFile(altered,'w') as dst:
        manifest=json.loads(src.read('BUILD_INFO.json'))
        for name in FILES:
            value=src.read(name)+(b'\n# unreviewed\n' if name=='local_agent.py' else b'')
            dst.writestr(name,value)
            manifest['files'][name]=hashlib.sha256(value).hexdigest()
        dst.writestr('BUILD_INFO.json',json.dumps(manifest))
    with pytest.raises(ValueError,match='GIT_BLOB'):
        verify(altered,expected_sha=head())
