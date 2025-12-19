#!/usr/bin/env python3
import requests
import sys

BASE = 'http://127.0.0.1:5000'


def fetch_expectations(staff_id='20172672', year='2025'):
    r = requests.get(f"{BASE}/api/expectations?staff_id={staff_id}&year={year}", timeout=10)
    r.raise_for_status()
    return r.json()


def test_resolves_hashed_id_to_base_task():
    """Server should resolve a hashed by-month task id to a base task and return a task-specific template"""
    staff_id = '20172672'
    year = '2025'

    j = fetch_expectations(staff_id, year)

    # pick a month and its first task
    by_month = j.get('by_month') or {}
    assert by_month, "Expectations by_month missing"
    first_month = next(iter(by_month.keys()))
    month_data = by_month.get(first_month) or {}
    # month_data may be a list of tasks or a dict containing a 'tasks' list
    month_tasks = month_data if isinstance(month_data, list) else (month_data.get('tasks') or [])
    assert month_tasks, "No tasks in first month"

    chosen = month_tasks[0]
    hashed_id = chosen.get('id')
    assert hashed_id, "Chosen task does not have an id"

    question = 'What evidence should I upload to meet this task?'

    context = {
        'staff_id': staff_id,
        'cycle_year': year,
        'scan_month': first_month,
        'current_tab': 'expectations',
        'expectations_count': j.get('task_count') or len(j.get('tasks') or []),
        'scan_results_count': 0,
        # only provide hashed id (no _baseId)
        'task': {
            'id': hashed_id,
            'title': chosen.get('title'),
            'kpa': chosen.get('kpa_name') or chosen.get('kpa_code'),
        }
    }

    rr = requests.post(f"{BASE}/api/ai/guidance", json={'question': question, 'context': context}, timeout=20)
    rr.raise_for_status()
    j2 = rr.json()

    # Expect template source and guidance containing task title or module references
    assert j2.get('source') == 'template', f"Unexpected source: {j2}"
    guidance = (j2.get('guidance') or '').lower()
    assert guidance, "No guidance text returned"
    assert (chosen.get('title').split()[0].lower() in guidance) or ('hise' in guidance) or ('module' in guidance), f"Guidance doesn't look task-specific: {guidance}"


if __name__ == '__main__':
    try:
        test_resolves_hashed_id_to_base_task()
        print('OK')
    except AssertionError as e:
        print('FAIL:', e)
        sys.exit(2)
    except Exception as e:
        print('ERROR:', e)
        sys.exit(3)
