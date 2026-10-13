"""One-click safe V4.4 Shadow switch. No Node.js, no database reset."""
from __future__ import annotations
import argparse
from datetime import datetime
from pathlib import Path
import re
import shutil

ROOT=Path(__file__).resolve().parent
ENV=ROOT/".env"
TEMPLATE=ROOT/".env.example"


def set_mode(mode: str) -> str:
    if not ENV.exists():
        if not TEMPLATE.exists():
            raise FileNotFoundError("Missing .env and .env.example")
        shutil.copy2(TEMPLATE, ENV)
    data=ENV.read_text(encoding="utf-8-sig")
    match=re.search(r"(?m)^\s*V44_SHADOW_ENABLED\s*=\s*(\S*)\s*$",data)
    current=(match.group(1).strip().lower() if match else "false")
    if mode=="status":
        return "enabled" if current=="true" else "disabled"
    intended="true" if mode=="enable" else "false"
    backup=ROOT/"backups"
    backup.mkdir(exist_ok=True)
    stamp=datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(ENV,backup/f".env-v44-{stamp}.bak")
    if match:
        updated=data[:match.start()]+f"V44_SHADOW_ENABLED={intended}"+data[match.end():]
    else:
        updated=data.rstrip()+"\nV44_SHADOW_ENABLED="+intended+"\n"
    ENV.write_text(updated,encoding="utf-8")
    return ("enabled" if intended=="true" else "disabled") + "; restart the Agent via run.bat"


if __name__=="__main__":
    parser=argparse.ArgumentParser(description="V4.4 Shadow mode switch")
    parser.add_argument("mode",choices=["enable","disable","status"])
    args=parser.parse_args()
    print("V4.4 Shadow: "+set_mode(args.mode))
