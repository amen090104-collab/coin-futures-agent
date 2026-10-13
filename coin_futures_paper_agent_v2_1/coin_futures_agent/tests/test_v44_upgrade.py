"""Windows-friendly upgrade helpers tested without touching user's local data."""
from pathlib import Path
import sqlite3

import configure_v44
import safe_preupdate_backup


def test_shadow_switch_preserves_existing_env_and_creates_backup(tmp_path, monkeypatch):
    env=tmp_path/".env"
    env.write_text("TOP_N_COINS=50\nREPORT_GITHUB_TOKEN=local_secret_placeholder\n",encoding="utf-8")
    (tmp_path/".env.example").write_text("V44_SHADOW_ENABLED=false\n",encoding="utf-8")
    monkeypatch.setattr(configure_v44,"ROOT",tmp_path)
    monkeypatch.setattr(configure_v44,"ENV",env)
    monkeypatch.setattr(configure_v44,"TEMPLATE",tmp_path/".env.example")
    assert configure_v44.set_mode("status")=="disabled"
    assert configure_v44.set_mode("enable").startswith("enabled")
    data=env.read_text(encoding="utf-8")
    assert "V44_SHADOW_ENABLED=true" in data
    assert "REPORT_GITHUB_TOKEN=local_secret_placeholder" in data
    assert configure_v44.set_mode("disable").startswith("disabled")
    assert "V44_SHADOW_ENABLED=false" in env.read_text(encoding="utf-8")
    assert list((tmp_path/"backups").glob(".env-v44-*.bak"))


def test_preupdate_backup_includes_wal_commits(tmp_path,monkeypatch):
    monkeypatch.setattr(safe_preupdate_backup,"ROOT",tmp_path)
    source=tmp_path/"agent.db"
    con=sqlite3.connect(source)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE paper_data (id INTEGER PRIMARY KEY,value TEXT)")
    con.execute("INSERT INTO paper_data(value) VALUES ('preserved')")
    con.commit()
    (tmp_path/".env").write_text("V44_SHADOW_ENABLED=true\n",encoding="utf-8")
    safe_preupdate_backup.backup()
    files=list((tmp_path/"backups").glob("agent-preupdate-*.db"))
    assert len(files)==1
    with sqlite3.connect(files[0]) as saved:
        assert saved.execute("SELECT value FROM paper_data").fetchone()[0]=="preserved"
        assert saved.execute("PRAGMA quick_check").fetchone()[0]=="ok"
    assert list((tmp_path/"backups").glob("env-preupdate-*.bak"))
    con.close()
