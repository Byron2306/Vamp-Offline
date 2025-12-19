#!/usr/bin/env python3
"""Generate one human-like guidance line per expectation task.
Outputs: backend/data/human_guidance_per_task.json
"""
import json
import random
import re
from pathlib import Path

# Config
EXPECTATIONS = Path("backend/data/staff_expectations/expectations_20172672_2025.json")
VALUES = Path("backend/data/nwu_brain/values_index.json")
KPA_GUIDE = Path("backend/data/nwu_brain/kpa_guidelines.md")
OUTPUT = Path("backend/data/human_guidance_per_task.json")

FORBIDDEN = r"[:\-–—\"'\*]"  # characters to remove
OPENERS = ["Nice work", "Great planning", "Well done", "Good to see this", "Impressive", "Lovely work", "Solid work", "Thanks for doing this"]


def clean(s: str) -> str:
    if not s:
        return ""
    s = re.sub(FORBIDDEN, "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def load_values():
    if not VALUES.exists():
        return []
    with open(VALUES, 'r', encoding='utf-8') as f:
        return json.load(f).get('core_values', [])


def pick_value_for_kpa(kpa: str, title: str, labels: list, examples: list, values_index: list):
    kpa_l = (kpa or '').lower()
    if 'social' in kpa_l or 'community' in kpa_l or 'respons' in kpa_l:
        return 'Social Responsiveness'
    if 'teach' in kpa_l or 'learn' in kpa_l or 'curriculum' in kpa_l:
        return 'Lifelong Learning'
    if 'research' in kpa_l or 'innovation' in kpa_l:
        return 'Innovation'
    # fallback: match keywords from values_index
    corpus = ' '.join([title or '', kpa or '', ' '.join(labels or []), ' '.join(examples or [])]).lower()
    best = None
    best_score = 0.0
    for v in values_index:
        score = 0.0
        for kw in v.get('keywords', []):
            pat = kw.get('pattern','')
            w = float(kw.get('weight',1.0))
            try:
                if re.search(pat, corpus):
                    score += w
            except re.error:
                if pat and pat in corpus:
                    score += w
        if score > best_score:
            best_score = score
            best = v.get('name')
    return best


def extract_kpa_examples(kpa: str):
    if not KPA_GUIDE.exists():
        return []
    text = KPA_GUIDE.read_text(encoding='utf-8')
    # find the KPA section by looking for header lines that include the kpa words
    parts = text.split('\n## ')
    kpa_l = (kpa or '').lower()
    for sec in parts:
        header = sec.split('\n',1)[0].lower()
        if kpa_l and any(word in header for word in kpa_l.split()):
            # collect first few list items as examples
            lines = [ln.strip().strip('- * ') for ln in sec.splitlines() if ln.strip().startswith('-')]
            return lines[:6]
    return []


def generate_for_task(task, values_index):
    title = task.get('title') or ''
    # Simplify title by removing leading month and parenthetical counts for readability
    title_core = title.split(':',1)[-1].strip() if ':' in title else title
    # remove parenthetical student counts
    title_core = re.sub(r"\([^)]*students?[^)]*\)", "", title_core)
    # normalize comma spacing
    title_core = re.sub(r"\s*,\s*", ", ", title_core)
    # drop module code tail after a hyphen for readability
    if ' - ' in title_core:
        title_core = title_core.split(' - ', 1)[0]
    # collapse whitespace and clean
    title_clean = clean(re.sub(r"\s+", " ", title_core).strip())
    hints = task.get('evidence_hints') or []

    # core evidence suggestions: prefer task hints then module-specific heuristics then generic
    evidence_suggestions = []
    for h in hints:
        if isinstance(h, str):
            hn = h.strip()
            if hn and hn not in evidence_suggestions:
                evidence_suggestions.append(hn)

    # detect module codes and student counts in title (e.g., HISE411 (35 students))
    module_match = re.findall(r"([A-Z]{3,}\d{3})\s*\((\d+)\s*students?\)", title)

    # If multiple modules are present, produce per-module suggestions for variety
    if module_match and len(module_match) > 1:
        per_module_lines = []
        for mcode, mcount in module_match:
            try:
                mcount = int(mcount)
            except Exception:
                mcount = None
            if mcount and mcount >= 40:
                mod_pref = ['an LMS screenshot or export', 'a gradebook export', 'a sample of anonymized student feedback']
            elif mcount and mcount >= 20:
                mod_pref = ['a slide deck', 'a sample of student feedback', 'an assessment rubric']
            else:
                mod_pref = ['a short reflective note', 'a sample student work']
            # pick top two for this module
            mod_ev = ', '.join(mod_pref[:2]) + ' or ' + mod_pref[2] if len(mod_pref) >= 3 else ', '.join(mod_pref)
            per_module_lines.append(f"For {mcode} consider {mod_ev}")
        # join module-specific lines and proceed to final instructions
        guidance = '. '.join(per_module_lines) + '. '
        guidance += 'Add a short one line note to each file and name files so they include the module code for easy lookup.'
        if any('ngo' in s for s in title.lower().split()):
            guidance += ' For external partners check goodwill permission or an MoU before sharing.'
        return clean(guidance)

    # single or no module: fall back to phase and module-size tailoring
    tailored = []
    if module_match:
        mcode, mcount = module_match[0]
        try:
            mcount = int(mcount)
        except Exception:
            mcount = None
        if mcount and mcount >= 40:
            tailored = ['an LMS screenshot or export', 'a gradebook export or aggregated marks summary', 'a sample of anonymized student feedback']
        elif mcount and mcount >= 20:
            tailored = ['a lecture slide deck', 'a sample of student feedback', 'an assessment rubric']
        else:
            tailored = ['a short reflective note', 'a sample student work or testimonial']

    # vary suggestions by task type keywords in title
    ttl = title.lower()
    if 'start' in ttl and 'semester' in ttl or ('start' in ttl):
        phase_tailored = ['a module outline', 'an LMS setup screenshot', 'orientation slides']
    elif 'teaching' in ttl or 'lecture' in ttl or 'tutorial' in ttl:
        phase_tailored = ['a lecture slide deck', 'an attendance list or register', 'tutorial materials or worksheets']
    elif 'mid' in ttl or 'mid-term' in ttl or 'midterm' in ttl:
        phase_tailored = ['a sample assessment with rubric', 'a short student feedback excerpt', 'a marking sample or moderation note']
    elif 'completion' in ttl or 'final' in ttl or 'exam' in ttl or 'year-end' in ttl:
        phase_tailored = ['a gradebook export', 'a moderation report', 'exam paper or mark sheet']
    else:
        phase_tailored = []

    # combine tailored suggestions (phase first, then module-size), and insert if not present
    for p in list(reversed(phase_tailored + tailored)):
        if p and p not in evidence_suggestions:
            evidence_suggestions.insert(0, p)

    # map common tokens to human phrases for readability
    mapped = []
    for ev in evidence_suggestions:
        ev_l = ev.lower()
        if 'lesson plan' in ev_l or 'planning' in ev_l or 'curriculum' in ev_l:
            mapped.append('a lesson plan')
        elif 'slide' in ev_l or 'slides' in ev_l:
            mapped.append('a slide deck')
        elif 'rubric' in ev_l or 'assessment' in ev_l:
            mapped.append('an assessment rubric')
        elif 'lms' in ev_l or 'efundi' in ev_l or 'blackboard' in ev_l:
            mapped.append('an LMS screenshot or export')
        elif 'report' in ev_l or 'outreach' in ev_l:
            mapped.append('an outreach report')
        elif 'lecture' in ev_l:
            mapped.append('a lecture slides or notes')
        else:
            mapped.append(ev)
    # dedupe while preserving order
    seen = set()
    evidence_suggestions = [x for x in mapped if not (x in seen or seen.add(x))]
    if not evidence_suggestions:
        evidence_suggestions = ['a clear primary artefact that shows the work']

    # permission flag
    lc = ' '.join([title.lower()] + hints + (task.get('labels') or []))
    needs_permission = any(w in lc for w in ['ngo','school','community','external','partner','municipal','stakeholder'])

    # opener sometimes omitted to avoid repetition
    opener = ''
    if random.random() < 0.4 and any(w in lc for w in ['school','community','ngo','outreach','partner']):
        opener = random.choice(OPENERS) + ' '
    else:
        # include a light praise randomly for other tasks
        if random.random() < 0.12:
            opener = random.choice(OPENERS) + ' '

    # Determine the evidence phrase from available hints
    top_evidence = evidence_suggestions[:3]
    if len(top_evidence) == 1:
        ev_text = top_evidence[0]
    elif len(top_evidence) == 2:
        ev_text = f"{top_evidence[0]} or {top_evidence[1]}"
    else:
        ev_text = ', '.join(top_evidence[:-1]) + f" or {top_evidence[-1]}"

    # Construct guidance focusing on the task itself and evidence
    guidance_parts = []
    if opener:
        guidance_parts.append(opener.strip())

    guidance_parts.append(f"For the task {title_clean}, consider {ev_text}.")
    guidance_parts.append("This helps reviewers understand what you did and when.")

    # short human friendly final instructions
    guidance_parts.append("Add a short one line note to each file stating what it is and the date.")
    guidance_parts.append("Name files so they include the module code or task name for easy lookup.")

    if needs_permission:
        guidance_parts.append("For external partners check goodwill permission or an MoU before sharing.")

    # join, clean and return
    text = ' '.join(guidance_parts)
    text = clean(text)
    return text


def main():
    if not EXPECTATIONS.exists():
        print('Expectations file missing:', EXPECTATIONS)
        return
    data = json.loads(EXPECTATIONS.read_text(encoding='utf-8'))
    tasks = data.get('tasks') or []
    values_idx = load_values()

    out = {}
    for t in tasks:
        gid = t.get('id')
        out[gid] = {
            'task_id': gid,
            'title': t.get('title'),
            'kpa': t.get('kpa_name') or t.get('kpa_code'),
            'guidance': generate_for_task(t, values_idx)
        }

    OUTPUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'Wrote {len(out)} guidance items to', OUTPUT)
    # print few samples
    for i, (k, v) in enumerate(out.items()):
        if i < 5:
            print('\n---', k, '---')
            print(v['guidance'])


if __name__ == '__main__':
    main()
