#!/usr/bin/env python3
import requests
import sys

BASE = 'http://127.0.0.1:5000'

def validate(staff_id, year):
    url = f"{BASE}/api/expectations?staff_id={staff_id}&year={year}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    j = r.json()

    id_map = j.get('_id_map', {})
    task_index = j.get('_task_index', {})
    by_month = j.get('by_month', {})

    errors = []
    for mk, md in by_month.items():
        tasks = md.get('tasks') or []
        for t in tasks:
            tid = t.get('id')
            base = t.get('_baseId') or t.get('task_id') or None
            if not tid:
                errors.append((mk, 'missing_id', t))
                continue
            # If tid is a hashed id, it should exist in id_map
            if tid in id_map:
                continue
            # else it may be the base id
            if base and base in task_index:
                continue
            errors.append((mk, 'unmapped', {'id': tid, 'base': base, 'title': t.get('title')}))

    print('checked', sum(len((md.get('tasks') or [])) for md in by_month.values()), 'by-month tasks')
    print('id_map size', len(id_map))
    if errors:
        print('errors:', len(errors))
        for e in errors[:20]:
            print(e)
        return 2
    print('OK: all by-month ids map to canonical ids or base ids')
    return 0

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Usage: validate_mappings.py <staff_id> <year>')
        sys.exit(1)
    sid = sys.argv[1]
    yr = sys.argv[2]
    sys.exit(validate(sid, yr))
