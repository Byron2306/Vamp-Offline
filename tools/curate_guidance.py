#!/usr/bin/env python3
"""Curate one polished guidance per KPA using generated human guidance and NWU data
Outputs: backend/data/curated_guidance_per_kpa.json
"""
import json
import random
import re
from pathlib import Path

HUMAN = Path('backend/data/human_guidance_per_task.json')
EXPECT = Path('backend/data/staff_expectations/expectations_20172672_2025.json')
VALUES = Path('backend/data/nwu_brain/values_index.json')
KPA_GUIDE = Path('backend/data/nwu_brain/kpa_guidelines.md')
OUT = Path('backend/data/curated_guidance_per_kpa.json')

OPENERS = ['Nice work', 'Great planning', 'Well done', 'Good to see this', 'Impressive', 'Lovely work']
FORBIDDEN_RE = re.compile(r"[:\-–—\"'\*]")


def clean(s):
    if not s:
        return ''
    s = FORBIDDEN_RE.sub('', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def load_json(p):
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding='utf-8'))


def pick_value_for_kpa(kpa):
    kpa_l = (kpa or '').lower()
    if 'social' in kpa_l or 'community' in kpa_l:
        return 'Social Responsiveness'
    if 'teach' in kpa_l or 'learn' in kpa_l or 'curriculum' in kpa_l:
        return 'Lifelong Learning'
    if 'research' in kpa_l or 'innovation' in kpa_l:
        return 'Innovation'
    if 'safety' in kpa_l or 'ohs' in kpa_l:
        return 'Accountability'
    return None


def simple_title(t):
    # drop month prefix and parenthetical counts
    core = t.split(':',1)[-1].strip() if ':' in t else t
    core = re.sub(r"\([^)]*students?[^)]*\)", '', core)
    core = re.sub(r"\s*,\s*", ', ', core)
    if ' - ' in core:
        core = core.split(' - ',1)[0]
    return clean(core)


def curate_one(task, human_text):
    title = simple_title(task.get('title',''))
    kpa = task.get('kpa_name') or task.get('kpa') or task.get('kpa_code') or ''
    val = pick_value_for_kpa(kpa)

    # pick 2-3 evidence phrases from human_text heuristically
    # look for phrases like 'lesson plan', 'slide deck', 'rubric', 'LMS', 'report'
    text = (human_text or '').lower()
    candidates = []
    if 'lesson' in text or 'lesson plan' in text or 'planning' in text:
        candidates.append('a lesson plan')
    if 'slide' in text or 'slide deck' in text:
        candidates.append('a slide deck')
    if 'rubric' in text or 'assessment' in text:
        candidates.append('an assessment rubric')
    if 'lms' in text or 'efundi' in text:
        candidates.append('an LMS screenshot or export')
    if 'report' in text or 'outreach' in text:
        candidates.append('an outreach report or summary')
    if not candidates:
        # fallback: take first three words from human_text
        w = ' '.join((human_text or '').split()[:4])
        candidates.append(clean(w))

    # construct guidance
    opener = ''
    if random.random() < 0.5:
        opener = random.choice(OPENERS) + ' '

    # make 2 evidence suggestions
    ev = candidates[:3]
    if len(ev) == 1:
        ev_text = ev[0]
    elif len(ev) == 2:
        ev_text = ev[0] + ' or ' + ev[1]
    else:
        ev_text = ', '.join(ev[:-1]) + ' or ' + ev[-1]

    parts = []
    if opener:
        parts.append(opener.strip())
    parts.append(f'You have prepared {title}')
    if val:
        parts.append(f'This activity reflects the NWU value {val} and supports the KPA')
    parts.append(f'Consider uploading {ev_text} as a primary artefact')
    parts.append('Add a one line note for each file stating what it is and the date and include the module or task name in the filename')

    # permission note if needed
    lc = ' '.join([title.lower(), (task.get('evidence_hints') or '') if isinstance(task.get('evidence_hints'), str) else ' '.join(task.get('evidence_hints') or [])])
    if any(w in lc for w in ['ngo','school','community','external','partner','municipal','stakeholder','outreach']):
        parts.append('For external partners check goodwill permission or a memorandum of understanding before sharing')

    out = ' '.join(parts)
    out = clean(out)
    return out


def main():
    expectations = load_json(EXPECT)
    human = load_json(HUMAN)
    tasks = expectations.get('tasks') or []

    # pick representative task per KPA in order KPA1..KPA5
    kpacodes = ['KPA1','KPA2','KPA3','KPA4','KPA5']
    selected = {}
    for code in kpacodes:
        for t in tasks:
            if t.get('kpa_code') == code:
                selected[code] = t
                break

    out = {}
    for code, t in selected.items():
        gid = t.get('id')
        human_text = (human.get(gid) or {}).get('guidance')
        polished = curate_one(t, human_text)
        out[code] = {
            'kpa_code': code,
            'kpa_name': t.get('kpa_name') or '',
            'task_id': gid,
            'task_title': simple_title(t.get('title','')),
            'guidance': polished
        }

    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
    print('Wrote curated KPA guidance to', OUT)
    for code, v in out.items():
        print('\n---', code, v.get('kpa_name'), '---')
        print(v.get('guidance'))


if __name__ == '__main__':
    main()
