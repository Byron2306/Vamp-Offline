#!/usr/bin/env python3
import requests
import sys

BASE='http://127.0.0.1:5000'

if __name__ == '__main__':
    staff_id='20172672'
    year='2025'
    try:
        r = requests.get(f"{BASE}/api/expectations?staff_id={staff_id}&year={year}", timeout=10)
        r.raise_for_status()
        j = r.json()
    except Exception as e:
        print('Could not fetch expectations:', e)
        sys.exit(2)

    by_month = j.get('by_month') or {}
    # find first month with tasks
    chosen_task=None
    for mk, md in by_month.items():
        tasks = md.get('tasks') or []
        if tasks:
            chosen_task = tasks[0]
            chosen_month = mk
            break

    if not chosen_task:
        print('No by-month tasks found')
        sys.exit(1)

    # Build context similar to collectContext
    context = {
        'staff_id': staff_id,
        'cycle_year': year,
        'stage': 'Stage: Expectations ready',
        'scan_month': chosen_month,
        'current_tab': 'expectations',
        'expectations_count': len(j.get('tasks') or []),
        'scan_results_count': 0,
        'task': {
            'id': chosen_task.get('id'),
            '_baseId': chosen_task.get('_baseId') or chosen_task.get('task_id') or None,
            '_canonicalId': chosen_task.get('_canonicalId') or None,
            'title': chosen_task.get('title'),
            'kpa': chosen_task.get('kpa_name') or chosen_task.get('kpa_code'),
            'goal': chosen_task.get('outputs') or chosen_task.get('what_to_do'),
            'cadence': chosen_task.get('cadence'),
            'minimum_count': chosen_task.get('minimum_count'),
            'stretch_count': chosen_task.get('stretch_count'),
            'evidence_hints': chosen_task.get('evidence_hints'),
            'evidence_required': chosen_task.get('evidence_required')
        }
    }

    question = 'What evidence should I upload to meet this task?'

    try:
        rr = requests.post(f"{BASE}/api/ai/guidance", json={'question': question, 'context': context}, timeout=20)
        rr.raise_for_status()
        print('AI guidance response:')
        print(rr.json())
    except Exception as e:
        print('AI guidance call failed:', e)
        sys.exit(3)
