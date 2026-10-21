"""Opt-in measured V5 acceptance. Read-only sources, separate outputs, no training or jobs."""
import argparse
import asyncio
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys

from .rei_v3_store import init, import_database, import_reports, coverage, samples, reconstruct_pending, reconstruct_entry_proxies
from .rei_v3_market import FuturesHistory
from .rei_v3_smoke import smoke
from .version import version_info


async def measure(db,*,reconstruct_limit=1,history=None):
    market=await smoke(db,history=history)
    owned=history is None
    history=history or FuturesHistory(db)
    try:
        restored=await reconstruct_pending(db,history,limit=reconstruct_limit)
        proxies=await reconstruct_entry_proxies(db,history,limit=reconstruct_limit)
    finally:
        if owned:await history.close()
    rows=samples(db)
    restored_ready=[row for row in rows if row['status']=='READY'
        and row.get('feature_provenance',{}).get('status')=='RECONSTRUCTED'
        and row['feature_provenance'].get('max_source_ms',row['decision_ms'])<row['decision_ms']
        and row['feature_provenance'].get('usable_at_original_signal') is True]
    return {'market':market,'coverage':coverage(db,rows),'reconstruction':restored,'proxy':proxies,
            'ready_signal_records':len(restored_ready),
            'restored_windows_proof':[row['feature_provenance'] for row in restored_ready[:3]],
            'point_in_time_verified':bool(restored_ready) and market['release_market_evidence'],
            'model_edge_verified':False,'training_performed':False,'strategies_or_env_changed':False}


def main():
    parser=argparse.ArgumentParser(description='Nghiem thu tren BAN SAO Windows; khong bat Shadow/real, khong sua nguon.')
    parser.add_argument('--output-dir',required=True,type=Path)
    parser.add_argument('--source-db',type=Path)
    parser.add_argument('--reports',type=Path)
    parser.add_argument('--confirm-disposable-copy',action='store_true')
    parser.add_argument('--reconstruct-limit',type=int,default=1)
    parser.add_argument('--expected-sha')
    args=parser.parse_args()
    if (args.source_db or args.reports) and not args.confirm_disposable_copy:
        parser.error('Chi dung ban sao; them --confirm-disposable-copy sau khi da chuan bi ban sao.')
    out=args.output_dir.resolve()
    if out.exists() or (args.reports and (out==args.reports.resolve() or args.reports.resolve() in out.parents)):
        parser.error('Chon thu muc output MOI nam ngoai reports nguon.')
    info=version_info()
    if args.expected_sha and info['sha']!=args.expected_sha:
        parser.error('Code SHA khong khop pin du kien; khong tao bang chung cho revision khac.')
    out.mkdir(parents=True)
    with closing(sqlite3.connect(out/'private-research.db')) as db:
        db.row_factory=sqlite3.Row;init(db)
        imports={}
        if args.source_db:
            with closing(sqlite3.connect(args.source_db.resolve().as_uri()+'?mode=ro',uri=True)) as source:
                source.row_factory=sqlite3.Row
                imports['database']=import_database(source,db)
        if args.reports:
            imports['reports']=import_reports(args.reports,db)
        db.commit()
        result=asyncio.run(measure(db,reconstruct_limit=max(0,min(50,args.reconstruct_limit))))
    ci=os.environ.get('GITHUB_ACTIONS')=='true'
    user_copy=os.name=='nt' and not ci and args.confirm_disposable_copy and bool(args.source_db or args.reports)
    result.update(code_sha=info['sha'],version=info['version'],python=sys.version.split()[0],platform=os.name,
                  ci=ci,windows_user_copy=user_copy,imports=imports,
                  input_kind='USER_SUPPLIED_READONLY_COPY_NOT_INDEPENDENTLY_AUDITED' if args.source_db or args.reports else 'PUBLIC_MARKET_ONLY_NO_PRIVATE_HISTORY',
                  not_release_authorization=True)
    result['meets_measured_release_gates']=bool(user_copy and result['point_in_time_verified'] and result['ready_signal_records']>=1)
    (out/'acceptance.redacted.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'market':result['market']['status'],'verified_windows':result['market']['verified_windows'],
        'ready_signal_records':result['ready_signal_records'],'windows_user_copy':user_copy,
        'meets_measured_release_gates':result['meets_measured_release_gates'],
        'next':'Nguoi bao tri can review bang chung; khong tu publish hoac bat model/Shadow/real.'},ensure_ascii=False))
    return 0 if result['meets_measured_release_gates'] else 2


if __name__=='__main__':
    raise SystemExit(main())
