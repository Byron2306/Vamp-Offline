#!/usr/bin/env python3
import json
from pathlib import Path

# Input expectations file (use the sample staff in the repo)
IN = Path('backend/data/staff_expectations/expectations_20172672_2025.json')
OUT = Path('backend/data/auto_guidance_templates.json')

if not IN.exists():
    print('Expectations file not found:', IN)
    raise SystemExit(1)

with IN.open('r') as f:
    data = json.load(f)

templates = []

# KPA level templates (one per KPA)
kpa_map = {}
for t in data.get('tasks',[]):
    kpa_code = t.get('kpa_code')
    kpa_name = t.get('kpa_name')
    if kpa_code and kpa_name and kpa_code not in kpa_map:
        kpa_map[kpa_code] = kpa_name

# Create KPA-level templates
for code,name in kpa_map.items():
    templates.append({
        'template_id': f'kpa_{code}_summary',
        'scope': {'kpa': name},
        'priority': 500,
        'metadata': {'author':'auto', 'version':'1.0'},
        'template_variants': {
            'short': f'For {name} tasks like {{title}}, prefer artefacts that directly evidence the outcome: primary artefacts (documents, datasets, or outputs) plus supporting materials. Aim for {{evidence_count}} clear items.',
            'detailed': f'{name} guidance for {{title}} ({{month}}): upload primary artefacts that directly demonstrate the outcome (e.g., curriculum documents, assessment rubrics, reports) and up to {{evidence_count}} supporting items such as emails, minutes, or reflections. Label each file with date and a 1-line explanation.'
        },
        'placeholders': {'title':'Task title', 'month':'Month', 'evidence_count':'Recommended count'}
    })

# Per-task templates
for t in data.get('tasks',[]):
    tid = t.get('id')
    title = t.get('title') or t.get('outputs') or ''
    kpa = t.get('kpa_name') or t.get('kpa') or ''
    hints = t.get('evidence_hints') or []
    evidence = t.get('evidence_required') or t.get('outputs') or ''
    min_count = t.get('minimum_count') or 1
    stretch = t.get('stretch_count') or min_count
    months = t.get('months') or []
    month_label = ('{{month}}')

    # Build specific short guidance using hints and evidence
    hint_sample = ', '.join(hints[:5]) if hints else ''
    short = f"Task-specific guidance for {title}: provide {min_count} primary artefact{'s' if min_count!=1 else ''} (e.g., {hint_sample}) that directly show the outcome. Label files with date and role."
    detailed = (
        f"Task: {title}\nKPA: {kpa}\nMonth: {month_label}\nRequired: Provide {min_count} primary artefacts and up to {stretch} supporting items. "
        f"Primary artefacts should be: {evidence if evidence else hint_sample}. "
        "When uploading, add a one-line note linking the artefact to the task outcome and include the date."
    )

    templates.append({
        'template_id': f'base_{tid}_guidance',
        'scope': {'base_task_id': tid},
        'priority': 1000,
        'metadata': {'author':'auto', 'version':'1.0'},
        'template_variants': {'short': short, 'detailed': detailed},
        'placeholders': {'title':'Task title','month':'Month','evidence_count':'Recommended count'}
    })

# Write output
OUT.parent.mkdir(parents=True, exist_ok=True)
with OUT.open('w') as f:
    json.dump(templates, f, indent=2)

print('Wrote', len(templates), 'templates to', OUT)
