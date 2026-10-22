"""Read-only experiment on an existing V5 research DB, independent output directory."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time

from .rei_v3_store import samples
from .rei_v3_learning import holdout
from .rei_v3_models import train, research_baseline
from .version import version_info


def experiment(db, *, now_ms):
    rows=samples(db);held=holdout(rows)
    old=db.execute("SELECT 1 FROM sqlite_master WHERE name='rei_v3_runs'").fetchone()
    if old:
        rec=db.execute("SELECT payload FROM rei_v3_runs WHERE run_id='holdout-v1'").fetchone()
        if rec:held=json.loads(rec[0])['groups']
    baseline=research_baseline(rows,now_ms=now_ms,held=held)
    online={side:train(rows,frozen_at_ms=now_ms,side=side,kind='FORWARD_FROZEN_MODEL',excluded_groups=held)
            for side in ('LONG','SHORT')}
    def public(m):return {k:v for k,v in m.items() if k not in {'model','calibrator','fit_groups','calibration_groups'}}
    return {'code':version_info(),'rows':len(rows),'measured_at_ms':now_ms,
        'historical_research':{'manifest':baseline['manifest'],'models':{s:public(m) for s,m in baseline['models'].items()},'per_side':baseline['per_side']},
        'forward_training_candidates':{s:public(m) for s,m in online.items()},
        'forward_decisions_evaluated':0,'qualified_real_money':False,'orders_created':0,
        'source_modified':False,'interpretation':'Local candidate training now is not a deployed frozen model or proof of forward profit.'},online


def main():
    p=argparse.ArgumentParser();p.add_argument('--source-db',required=True,type=Path);p.add_argument('--output-dir',required=True,type=Path)
    a=p.parse_args();source=a.source_db.resolve();out=a.output_dir.resolve()
    if out.exists() or out==source or source in out.parents:p.error('OUTPUT_MUST_BE_NEW_SEPARATE_DIRECTORY')
    try:
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            report,models=experiment(db,now_ms=int(time.time()*1000))
        out.mkdir(parents=True)
        (out/'experiment.redacted.json').write_text(json.dumps(report,ensure_ascii=True,indent=2,allow_nan=False),encoding='ascii')
        (out/'private-models.json').write_text(json.dumps(models,ensure_ascii=True,allow_nan=False),encoding='ascii')
        print('V3_EXPERIMENT_COMPLETE_READONLY_NO_ORDERS');return 0
    except (OSError,ValueError,TypeError,KeyError,sqlite3.Error):
        print('V3_EXPERIMENT_BLOCKED_NO_SOURCE_CHANGED');return 1


if __name__=='__main__':raise SystemExit(main())
