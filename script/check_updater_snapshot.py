#!/usr/bin/env python3
"""Detect drift in the application-independent vendored updater snapshot."""
import argparse
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def snapshot(root):
    paths=sorted(p for p in (root/'updater').rglob('*') if p.is_file() and p.name!='SNAPSHOT.json')
    paths += [root/'script'/name for name in ('tlo_update_release.py','qualify_updates.py','test_tlo_update_release.py','check_updater_snapshot.py')]
    missing=[str(p) for p in paths if not p.is_file()]
    if missing: raise SystemExit('Incomplete updater snapshot: '+', '.join(missing))
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--write',action='store_true');p.add_argument('--compare',type=Path);a=p.parse_args()
    current=snapshot(ROOT);path=ROOT/'updater/SNAPSHOT.json'
    if a.write:path.write_text(json.dumps(current,sort_keys=True,indent=2)+'\n')
    if json.loads(path.read_text())!=current:raise SystemExit('Updater snapshot changed: review and refresh SNAPSHOT.json')
    if a.compare and snapshot(a.compare)!=current:raise SystemExit('Updater consumers have different shared snapshots')
    print('Shared updater snapshot verified')
