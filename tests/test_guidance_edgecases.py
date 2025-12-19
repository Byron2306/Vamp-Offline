#!/usr/bin/env python3
import requests
import os
import sys

BASE = 'http://127.0.0.1:5000'


def test_no_task_context_returns_generic_template():
    """If no task info is provided, the server should return a generic guidance template"""
    context = {
        'staff_id': '20172672',
        'cycle_year': '2025',
        'current_tab': 'expectations'
    }
    rr = requests.post(f"{BASE}/api/ai/guidance", json={'question': 'What should I upload?', 'context': context}, timeout=20)
    rr.raise_for_status()
    j = rr.json()
    assert 'guidance' in j
    assert j.get('source') in ('template', 'generated', 'llm')
    # Prefer to see the generic template id when template source is used
    if j.get('source') == 'template':
        assert 'generic' in (j.get('template_id') or '').lower()


def test_top_level_task_id_recovery():
    """If the context contains task id at top level (task_id), server should resolve it"""
    # Use a known hashed task id from sample expectations
    hashed = 'c4043bba78d949'
    context = {
        'staff_id': '20172672',
        'cycle_year': '2025',
        'scan_month': '2025-01',
        'task_id': hashed
    }
    rr = requests.post(f"{BASE}/api/ai/guidance", json={'question': 'What evidence?', 'context': context}, timeout=20)
    rr.raise_for_status()
    j = rr.json()
    assert 'guidance' in j
    # should be template-backed and task-specific
    assert j.get('source') in ('template', 'generated')
    guidance = (j.get('guidance') or '').lower()
    assert guidance
    assert ('module' in guidance) or ('hise' in guidance) or ('lesson' in guidance)


def test_provide_baseId_prioritizes_task_template():
    """When context.task includes _baseId, server should return a task-specific guidance (not generic)"""
    context = {
        'staff_id': '20172672',
        'cycle_year': '2025',
        'scan_month': '2025-01',
        'task': {
            'id': 'c4043bba78d949',
            '_baseId': 'task_001',
            'title': 'Jan: Module planning & curriculum design - HISE411',
            'kpa': 'Teaching and Learning'
        }
    }
    rr = requests.post(f"{BASE}/api/ai/guidance", json={'question': 'Evidence for this task', 'context': context}, timeout=20)
    rr.raise_for_status()
    j = rr.json()
    assert 'guidance' in j
    # should be template-backed and not be the global generic
    if j.get('source') == 'template':
        tid = (j.get('template_id') or '')
        assert 'generic' not in tid.lower(), f"Unexpected generic template selected: {tid}"


def test_unknown_task_id_uses_generator_or_fallback():
    """If unknown task id is given, server should still provide useful guidance via generator or LLM"""
    context = {
        'staff_id': '20172672',
        'cycle_year': '2025',
        'task': {'id': 'no_such_task_id', 'title': 'Nonexistent Task', 'kpa': 'KPA1'}
    }
    rr = requests.post(f"{BASE}/api/ai/guidance", json={'question': 'How to evidence this?', 'context': context}, timeout=20)
    rr.raise_for_status()
    j = rr.json()
    assert 'guidance' in j
    assert j.get('source') in ('generated', 'template', 'llm')
    assert j.get('guidance')


if __name__ == '__main__':
    try:
        test_no_task_context_returns_generic_template()
        test_top_level_task_id_recovery()
        test_provide_baseId_prioritizes_task_template()
        test_unknown_task_id_uses_generator_or_fallback()
        print('OK')
    except AssertionError as e:
        print('FAIL:', e)
        sys.exit(2)
    except Exception as e:
        print('ERROR:', e)
        sys.exit(3)
