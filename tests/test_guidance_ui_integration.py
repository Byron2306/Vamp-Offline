#!/usr/bin/env python3
import requests
import sys

BASE = 'http://127.0.0.1:5000'


def test_simulated_ai_button_flow():
    """Simulate frontend flow: get expectations, pick by-month task and call guidance endpoint as the UI would"""
    staff_id = '20172672'
    year = '2025'

    # Get expectations (as UI would)
    r = requests.get(f"{BASE}/api/expectations?staff_id={staff_id}&year={year}", timeout=10)
    r.raise_for_status()
    j = r.json()

    by_month = j.get('by_month') or {}
    assert by_month, 'No by_month data'

    # Emulate user clicking the AI button for the first task in the first month
    month_key = next(iter(by_month.keys()))
    month_data = by_month[month_key] or {}
    tasks = month_data if isinstance(month_data, list) else (month_data.get('tasks') or [])
    assert tasks, 'No tasks in month'

    chosen = tasks[0]
    task_id = chosen.get('id')
    # Emulate minimal context the UI sends (collectContext)
    context = {
        'staff_id': staff_id,
        'cycle_year': year,
        'scan_month': month_key,
        'current_tab': 'expectations',
        'expectations_count': j.get('task_count') or len(j.get('tasks') or []),
        'scan_results_count': 0,
        'task': {
            'id': task_id,
            # note: the real UI would try to include _baseId when it knows it, but when it doesn't,
            # the server should still resolve it
            'title': chosen.get('title'),
            'kpa': chosen.get('kpa_name') or chosen.get('kpa_code')
        }
    }

    question = 'Quick: what evidence should I upload?'
    rr = requests.post(f"{BASE}/api/ai/guidance", json={'question': question, 'context': context}, timeout=20)
    rr.raise_for_status()
    res = rr.json()

    # we expect a deterministic template or generated short_personal guidance
    assert res.get('source') in ('template', 'generated'), f"Unexpected source: {res}"
    guidance = (res.get('guidance') or '').strip()
    assert guidance, 'Empty guidance'
    print('GUIDANCE:', guidance)


if __name__ == '__main__':
    try:
        test_simulated_ai_button_flow()
        print('OK')
    except AssertionError as e:
        print('FAIL:', e)
        sys.exit(2)
    except Exception as e:
        print('ERROR:', e)
        sys.exit(3)
