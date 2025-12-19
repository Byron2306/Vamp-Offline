#!/usr/bin/env python3
"""Generate multiple human guidance variants for a subset of tasks.
Outputs: backend/data/human_guidance_samples.json
"""
import json
import random
import re
from pathlib import Path

HUMAN = Path('backend/data/human_guidance_per_task.json')
EXPECT = Path('backend/data/staff_expectations/expectations_20172672_2025.json')
OUT = Path('backend/data/human_guidance_samples.json')

# variants to produce
VARIANT_TYPES = ['friendly', 'concise', 'coach']


def simple_title(t):
    core = t.split(':',1)[-1].strip() if ':' in t else t
    core = re.sub(r"\([^)]*students?[^)]*\)", '', core)
    core = re.sub(r"\s*,\s*", ', ', core)
    if ' - ' in core:
        core = core.split(' - ',1)[0]
    core = re.sub(r'[:\-–—"\'"\*]', '', core)
    return re.sub(r'\s+', ' ', core).strip()


def derive_evidence_hint(guidance_text):
    # Heuristically pull a short evidence phrase from existing guidance
    # Prefer explicit 'consider' or 'start with' phrasing when present
    if not guidance_text:
        return 'a clear artefact'
    t = guidance_text.lower()
    # try to extract after 'consider' or 'start with'
    m = re.search(r"(?:consider|start with|consider uploading)\s+([^\.]+)", t, flags=re.I)
    if m:
        hint = m.group(1).strip()
        # drop leading 'for the task' or similar accidental repeats
        hint = re.sub(r"^for the task\b", '', hint, flags=re.I).strip()
        # if hint is too short or generic, fall back
        if len(hint.split()) >= 2 and not hint.lower().startswith('for the task'):
            # remove trailing phrases like 'this helps reviewers' if present
            hint = re.split(r"\. | this ", hint, maxsplit=1)[0].strip()
            # split into candidates by commas or ' or '
            parts = re.split(r",| or ", hint)
            parts = [p.strip() for p in parts if p.strip()]
            # normalize into phrases with articles
            out = []
            for p in parts[:3]:
                if not re.match(r'^(a|an|the)\b', p):
                    p = re.sub(r'^my\b', '', p).strip()
                    p = 'a ' + p
                out.append(p)
            return out
    # fallback to pattern matching for known evidence types
    candidates = []
    if 'lesson plan' in t or 'planning' in t or 'curriculum' in t:
        candidates.append('a lesson plan')
    if 'slide' in t or 'slides' in t:
        candidates.append('a slide deck')
    if 'rubric' in t or 'assessment' in t:
        candidates.append('an assessment rubric')
    if 'lms' in t or 'efundi' in t:
        candidates.append('an LMS screenshot or export')
    if 'report' in t or 'outreach' in t:
        candidates.append('an outreach report')
    if 'lecture' in t:
        candidates.append('lecture slides or notes')
    if candidates:
        return candidates[:3]
    # final fallback: first meaningful words (up to 4)
    words = [w for w in re.findall(r"\w+", guidance_text) if len(w) > 2]
    if words:
        candidate = ' '.join(words[:4])
        if not re.match(r'^(a|an|the)\b', candidate.lower()):
            candidate = 'a ' + candidate
        return [candidate]
    return ['a clear artefact']


def make_variants(title, base_text):
    ev_list = derive_evidence_hint(base_text)
    if isinstance(ev_list, str):
        ev_list = [ev_list]
    # ensure up to 3, formatted as 'a x, y or z'
    evs = ev_list[:3]
    if len(evs) == 1:
        ev_text = evs[0]
    elif len(evs) == 2:
        ev_text = f"{evs[0]} or {evs[1]}"
    else:
        ev_text = ', '.join(evs[:-1]) + f" or {evs[-1]}"
    # Normalize capitalization and articles
    ev_text = re.sub(r"\blms\b", "LMS", ev_text, flags=re.I)
    # Fix article before export/exam/outreach if needed
    ev_text = re.sub(r"\ba\s+(export|exam|outreach)\b", r"an \1", ev_text, flags=re.I)
    # Fix article before single-letter acronyms like L
    ev_text = re.sub(r"\ba\s+([lL][A-Za-z0-9]+)\b", r"an \1", ev_text)

    variants = {}
    variants['friendly'] = f"For the task {title}, consider {ev_text}. This helps reviewers understand your work and its impact. Please add a short one line note to each file and include the module or task name in the filename"
    variants['concise'] = f"Task {title}: {ev_text}. Add one-line notes and name files with module or task for lookup"
    variants['coach'] = f"Coach tip For {title} ask for {ev_text} and a 1-line reflection linking the artefact to the task outcome"
    return variants


def main():
    if not HUMAN.exists() or not EXPECT.exists():
        print('Required data missing')
        return
    human = json.loads(HUMAN.read_text(encoding='utf-8'))
    exp = json.loads(EXPECT.read_text(encoding='utf-8'))
    tasks = exp.get('tasks') or []

    # pick 30 tasks evenly across task list
    n = min(30, len(tasks))
    step = max(1, len(tasks) // n)
    picked = [tasks[i] for i in range(0, len(tasks), step)][:n]

    out = {}
    for t in picked:
        tid = t.get('id')
        title = simple_title(t.get('title',''))
        base = human.get(tid,{}).get('guidance','')
        vars = make_variants(title, base)
        out[tid] = {
            'task_id': tid,
            'title': title,
            'kpa': t.get('kpa_name') or t.get('kpa_code') or '',
            'variants': vars
        }

    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Wrote {len(out)} sample tasks to', OUT)
    # print a few
    for i,(k,v) in enumerate(out.items()):
        if i<6:
            print('\n---', k, v['title'], '---')
            for vt,txt in v['variants'].items():
                print(f'[{vt}]', txt)


if __name__=='__main__':
    main()
