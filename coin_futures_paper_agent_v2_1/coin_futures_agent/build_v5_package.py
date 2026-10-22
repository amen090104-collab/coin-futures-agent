"""Build/verify the single extractable V2 -> V5 package from a full reviewed Git pin."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

from v5_package import APP_SUBDIR, INFO, SOURCES, materialize, verify_folder, verify_git, sha256


def git(*args,root=None,binary=False):
    result=subprocess.run(['git',*args],cwd=root or Path(__file__).resolve().parent,capture_output=True,check=True)
    return result.stdout if binary else result.stdout.decode('utf-8').strip()


def build(output,*,expected_sha,root=None):
    if git('rev-parse','HEAD',root=root)!=expected_sha:
        raise ValueError('V5_PACKAGE_MUST_MATCH_REVIEWED_HEAD')
    with tempfile.TemporaryDirectory() as directory:
        manifest=materialize(directory,expected_sha,lambda name:git('cat-file','blob',expected_sha+':'+APP_SUBDIR+'/'+name,root=root,binary=True))
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for name in (*SOURCES,INFO):
                member=zipfile.ZipInfo(name,date_time=(2020,1,1,0,0,0));member.compress_type=zipfile.ZIP_DEFLATED
                archive.writestr(member,(Path(directory)/name).read_bytes())
    verify(output,expected_sha=expected_sha,root=root)
    return manifest


def verify(archive_path,*,expected_sha,root=None):
    with tempfile.TemporaryDirectory() as directory, zipfile.ZipFile(archive_path) as archive:
        if set(archive.namelist())!={*SOURCES,INFO} or len(archive.namelist())!=len(SOURCES)+1:
            raise ValueError('V5_ARCHIVE_UNEXPECTED_FILES')
        if any(info.file_size>2*1024*1024 or ((info.external_attr>>16)&0o170000)==0o120000 for info in archive.infolist()):
            raise ValueError('V5_ARCHIVE_INVALID_MEMBER')
        archive.extractall(directory)
        manifest=verify_folder(directory)
        if manifest['source_sha']!=expected_sha:
            raise ValueError('V5_ARTIFACT_PIN_MISMATCH')
        verify_git(manifest,lambda *args,**kwargs:git(*args,root=root,**kwargs))
        return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('output',type=Path)
    parser.add_argument('--expected-sha',required=True)
    parser.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    result=verify(args.output,expected_sha=args.expected_sha) if args.verify else build(args.output,expected_sha=args.expected_sha)
    if not args.verify:
        checksum=sha256(args.output.read_bytes())
        Path(str(args.output)+'.sha256').write_text(checksum+'  '+args.output.name+'\n',encoding='utf-8')
        if os.environ.get('GITHUB_ACTIONS')=='true':
            print('::notice title=V5 package SHA256::source_sha='+result['source_sha']+' zip_sha256='+checksum,flush=True)
    print('V5 package verified:',result['source_sha'],'files:',len(result['files']),'manual pinned installation available')
