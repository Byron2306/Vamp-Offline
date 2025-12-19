#!/usr/bin/env python3
"""Import per-task human guidance into backend/data/guidance_templates.json
Creates high-priority templates scoped by base_task_id so the UI prefers them.
"""
import json
from pathlib import Path
from datetime import datetime

HUMAN = Path('backend/data/human_guidance_per_task.json')
TEMPLATES = Path('backend/data/guidance_templates.json')
OUT = TEMPLATES

if not HUMAN.exists():
    print('Human guidance file missing:', HUMAN)
    raise SystemExit(1)
if not TEMPLATES.exists():
    print('Templates file missing:', TEMPLATES)
    raise SystemExit(1)

human = json.loads(HUMAN.read_text(encoding='utf-8'))
tpls = json.loads(TEMPLATES.read_text(encoding='utf-8'))
if not isinstance(tpls, list):
    # support top-level object with 'templates' key
    if isinstance(tpls, dict) and 'templates' in tpls:
        tlist = tpls['templates']
    else:
        print('Unexpected templates file structure')
        raise SystemExit(1)
else:
    tlist = tpls

existing_ids = {t.get('template_id') for t in tlist}
added = 0
now = datetime.utcnow().isoformat() + 'Z'

for tid, entry in human.items():
    # create template id
    tid_name = f"human_task_{tid}"
    if tid_name in existing_ids:
        continue
    # for variants: convert our single guidance to short/detailed and generate coach
    friendly = entry.get('guidance')
    # build concise version (shorten first sentence)
    concise = friendly
    # coach: short coaching prompt
    coach = f"Coach tip For {entry.get('title')} ask for {friendly.split('consider',1)[-1].strip()} and a short 1 line reflection linking the artefact to the task outcome"
    tmpl = {
        "template_id": tid_name,
        "scope": {"base_task_id": tid},
        "priority": 5000,
        "metadata": {"author": "generated-human", "version": "1.0", "locale": "en", "created_at": now},
        "template_variants": {
            "short": friendly,
            "detailed": concise,
            "coach": coach
        },
        "placeholders": {"title": "Task title", "month": "Month"}
    }
    tlist.append(tmpl)
    existing_ids.add(tid_name)
    added += 1

# write back - preserve original top-level structure if present
if isinstance(tpls, dict) and 'templates' in tpls:
    tpls['templates'] = tlist
    OUT.write_text(json.dumps(tpls, indent=2, ensure_ascii=False), encoding='utf-8')
else:
    OUT.write_text(json.dumps(tlist, indent=2, ensure_ascii=False), encoding='utf-8')

print(f'Added {added} human task templates to {OUT}')
# print a few added ids
count=0
for t in tlist[::-1]:
    if t.get('template_id','').startswith('human_task_'):
        print(t.get('template_id'), '-', t.get('scope'))
        count+=1
        if count>=5:
            break
