"""Install local launchers beside an existing V2 checkout, without changing tracked files."""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import sys

FILES = ('local_agent.py', 'local_update.py', 'safe_preupdate_backup.py', 'approved_release.json')


def install(target, desktop, *, source=None):
    target, desktop = Path(target).resolve(), Path(desktop).resolve()
    source = Path(source or Path(__file__).parent)
    if not (target/'app'/'main.py').is_file() or not (target/'requirements.txt').is_file():
        raise ValueError('SELECT_EXISTING_AGENT_APP_FOLDER')
    check = subprocess.run(['git','rev-parse','--is-inside-work-tree'], cwd=target, capture_output=True, timeout=10)
    if check.returncode or check.stdout.strip() != b'true':
        raise ValueError('TARGET_MUST_BE_EXISTING_GIT_INSTALL')
    for name in FILES:
        if not (source/name).is_file():
            raise ValueError('INCOMPLETE_REVIEWED_BOOTSTRAP_PACKAGE')
    bootstrap = target/'.agent-updater'/'bootstrap'
    bootstrap.mkdir(parents=True, exist_ok=True)
    # Do not replace a locally approved pin on subsequent setup.
    for name in FILES:
        destination = bootstrap/name
        if name == 'approved_release.json' and destination.exists():
            continue
        shutil.copy2(source/name, destination)
    desktop.mkdir(parents=True, exist_ok=True)
    for name, action in (('CAP_NHAT_AGENT','update'),('CHAY_AGENT','run'),('QUAY_LAI_BAN_CU','rollback')):
        # CMD expands percent even inside quotes. Paths with spaces/Unicode/& remain quoted.
        quote = lambda value: '"'+str(value).replace('%','%%')+'"'
        text = '@echo off\nsetlocal DisableDelayedExpansion\n'+quote(sys.executable)+' '+quote(bootstrap/'local_update.py')+' '+action+' --root '+quote(target)+'\npause\n'
        # UTF-8 console for batch paths; Python itself receives native Unicode arguments.
        text = text.replace('setlocal DisableDelayedExpansion\n','setlocal DisableDelayedExpansion\nchcp 65001 >nul\n')
        (desktop/(name+'.bat')).write_text(text, encoding='utf-8', newline='\r\n')
    return bootstrap


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--target',type=Path)
    parser.add_argument('--desktop',type=Path)
    args=parser.parse_args()
    if sys.version_info < (3,12):
        print('Can Python 3.12+; khuyen nghi 3.13.5.')
        return 1
    target=args.target
    if target is None:
        from tkinter import Tk, filedialog
        window=Tk()
        window.withdraw()
        selected=filedialog.askdirectory(title='Chon thu muc Agent cu co app, agent.db va .env')
        window.destroy()
        if not selected:
            return 1
        target=Path(selected)
    desktop=args.desktop
    if desktop is None:
        if os.name=='nt':
            import ctypes
            buffer=ctypes.create_unicode_buffer(32768)
            if ctypes.windll.shell32.SHGetFolderPathW(None,0x10,None,0,buffer)!=0:
                return 1
            desktop=Path(buffer.value)
        else:
            desktop=Path.home()/'Desktop'
    try:
        install(target,desktop)
    except (OSError,ValueError,subprocess.SubprocessError):
        print('Khong cai dat. Can Git, Python va thu muc Agent cu hop le. Khong thay DB/.env.')
        return 1
    print('Da tao CAP_NHAT_AGENT, CHAY_AGENT, QUAY_LAI_BAN_CU tren Desktop. Dung cua so agent cu bang Ctrl+C truoc khi chay.')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
