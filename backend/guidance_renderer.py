import json
import random
from typing import List, Dict, Any, Optional
from pathlib import Path
import re


class SafeDict(dict):
    def __missing__(self, key):
        return ""


def load_templates(path: str or Path) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            # support top-level object with 'templates' key
            if isinstance(data, dict) and 'templates' in data:
                return data['templates']
    except Exception:
        return []
    return []
    

def matches_scope(template: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    scope = template.get('scope') or {}
    # Exact base_task_id match
    base = scope.get('base_task_id')
    if base and ctx.get('task') and (ctx['task'].get('_baseId') == base or ctx['task'].get('base_id') == base or ctx['task'].get('task_id') == base):
        return True
    # KPA match
    kpa = scope.get('kpa')
    if kpa and ctx.get('task') and (ctx['task'].get('kpa') == kpa or ctx['task'].get('kpa_code') == kpa):
        return True
    # tags match
    tags = scope.get('tags') or []
    if tags and ctx.get('task'):
        task_tags = ctx['task'].get('tags') or []
        if any(t in task_tags for t in tags):
            return True
    # title_regex (substring fallback)
    title_regex = scope.get('title_regex')
    if title_regex and ctx.get('task'):
        title = ctx['task'].get('title') or ''
        if title_regex in title:
            return True
    # If no scope entries, it's a global template
    if not scope:
        return True
    return False


def pick_best_template(templates: List[Dict[str, Any]], ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    matches = [t for t in templates if matches_scope(t, ctx)]
    if not matches:
        return None
    matches.sort(key=lambda x: int(x.get('priority', 0)), reverse=True)
    return matches[0]
    

def render_template(template: Dict[str, Any], ctx: Dict[str, Any], variant: str = 'short') -> str:
    variants = template.get('template_variants') or {}
    text = variants.get(variant) or variants.get('detailed') or variants.get('short') or template.get('template_text') or ''
    try:
        text = text.replace('{{', '{').replace('}}', '}')
    except Exception:
        pass
    task = ctx.get('task') or {}
    token_map = {}
    token_map.update({
        'staff_name': ctx.get('staff_name') or ctx.get('staff') or '',
        'month': ctx.get('month') or ctx.get('cycle_month') or '',
        'base_task_id': task.get('_baseId') or task.get('task_id') or task.get('id') or '',
        'canonical_id': task.get('_canonicalId') or task.get('id') or '',
        'title': task.get('title') or task.get('task') or '',
        'kpa': task.get('kpa') or task.get('kpa_code') or '',
        'target': task.get('target') or task.get('lead_target') or task.get('lag_target') or '',
        'evidence_count': str(task.get('evidence_count') or task.get('evidence_items') or task.get('minimum_count') or task.get('min_required') or 2),
        'examples': ', '.join(task.get('evidence_hints') or [])
    })

    try:
        rendered = text.format_map(SafeDict(token_map))
    except Exception:
        rendered = text
        for k, v in token_map.items():
            rendered = rendered.replace('{{' + k + '}}', str(v))
    return rendered


def render_best_template(templates: List[Dict[str, Any]], ctx: Dict[str, Any], variant: str = 'short') -> Optional[Dict[str, Any]]:
    tmpl = pick_best_template(templates, ctx)
    if not tmpl:
        return None
    text = render_template(tmpl, ctx, variant=variant)
    return {
        'template_id': tmpl.get('template_id'),
        'source': 'template',
        'text': text,
        'metadata': tmpl.get('metadata', {})
    }


def get_rendered_template(path: str or Path, ctx: Dict[str, Any], variant: str = 'short') -> Optional[Dict[str, Any]]:
    templates = load_templates(path)
    if not templates:
        return None
    return render_best_template(templates, ctx, variant=variant)


def generate_qualitative_guidance(ctx: Dict[str, Any], variant: str = 'detailed') -> Dict[str, Any]:
    """
    Produce a rigorous, targeted, qualitative guidance string based on the task context.
    This is used when no template matches or when we want a deterministic high-quality
    fallback that is not generic.
    """
    task = (ctx or {}).get('task') or {}
    title = task.get('title') or task.get('task') or 'this task'
    kpa = task.get('kpa') or task.get('kpa_code') or 'Unknown KPA'
    month = ctx.get('month') or ctx.get('cycle_month') or ctx.get('scan_month') or ''
    min_req = int(task.get('minimum_count') or task.get('min_required') or 0)
    stretch = int(task.get('stretch_count') or task.get('stretch_target') or min_req)
    hints = task.get('evidence_hints') or []
    evidence_required = task.get('evidence_required') or ''

    # Prefer explicit hints supplied in ctx['task'] (labels, examples, file_patterns, supports_kpis)
    preferred_examples: List[str] = []
    supports_kpis = task.get('supports_kpis') or task.get('supports') or []
    file_patterns = task.get('file_patterns') or []
    labels = task.get('labels') or []
    examples = task.get('examples') or task.get('evidence_hints') or []

    # Use examples/file_patterns/labels first when available
    if examples:
        preferred_examples.extend([e for e in examples if isinstance(e, str)])
    if file_patterns and not preferred_examples:
        # convert simple file patterns into example descriptions
        for fp in file_patterns[:3]:
            preferred_examples.append(f"files matching '{fp}'")

    # As a fallback, try to read the taxonomy file for broad KPA examples
    if not preferred_examples:
        taxonomy_path = Path(__file__).resolve().parent / 'knowledge' / 'evidence_taxonomy.json'
        try:
            with open(taxonomy_path, 'r', encoding='utf-8') as tf:
                tax = json.load(tf)
                # Look for kpa or task entries
                for entry in tax.get('tasks', []) or []:
                    if (entry.get('base_task_id') and entry.get('base_task_id') == task.get('_baseId')):
                        preferred_examples.extend(entry.get('examples') or [])
                        if not supports_kpis:
                            supports_kpis = entry.get('supports_kpis') or supports_kpis
                        if not labels:
                            labels = entry.get('labels') or labels
                        break
                # fallback to kpa-level examples
                if not preferred_examples:
                    for kentry in tax.get('kpas', []) or []:
                        name = kentry.get('kpa') or kentry.get('id') or ''
                        if name and kpa and kpa.lower() in name.lower():
                            preferred_examples.extend(kentry.get('examples') or [])
                            if not supports_kpis:
                                supports_kpis = kentry.get('supports_kpis') or supports_kpis
                            if not labels:
                                labels = kentry.get('labels') or labels
                            break
        except Exception:
            preferred_examples = preferred_examples

    # Short, personal variant: brief task summary + tips (no numeric identifiers)
    if variant == 'short_personal':
        # Build a friendly, personal summary and three concise tips
        # Avoid punctuation characters: colons, dashes, quotation marks, asterisks
        def clean(s: str) -> str:
            if not s:
                return ''
            return s.replace(':', '').replace('-', ' ').replace('–', ' ').replace('—', ' ').replace('"', '').replace("'", '').replace('*', '')

        title_clean = clean(title)

        # Friendly opener when community or outreach is involved
        opener = ''
        lc = (title + ' ' + ' '.join(examples or []) + ' ' + ' '.join(labels or [])).lower()
        if any(word in lc for word in ['school', 'community', 'outreach', 'ngo', 'stakeholder', 'municipal', 'volunteer']):
            # vary opener usage to avoid repetition — include only some of the time
            if random.random() < 0.35:
                openers = ["Wow impressive", "Nice work", "Great initiative", "Good to see this", "Well done"]
                opener_sentences = [random.choice(openers)]
                found_place = None
                for word in ['high school', 'primary school', 'school', 'ngo', 'municipality']:
                    if word in lc:
                        found_place = word
                        break
                if found_place:
                    opener_sentences.append(f"You are showing real willingness to participate in the local community especially the {found_place}")
                else:
                    opener_sentences.append("You are showing real willingness to participate in the local community")
                opener = ' '.join(opener_sentences)

        # One-line task summary without colon or quotes
        summary = f"This task is {title_clean}."

        # Personal tips: three concise suggestions without numeric values
        tips: List[str] = []
        def nl_join(items: List[str]) -> str:
            items = [str(i) for i in items]
            if not items:
                return ''
            if len(items) == 1:
                return items[0]
            if len(items) == 2:
                return items[0] + ' or ' + items[1]
            return ', '.join(items[:-1]) + ' or ' + items[-1]

        if preferred_examples:
            tips.append(clean(f"Prefer clear items such as {nl_join(preferred_examples[:3])}"))
        elif file_patterns:
            tips.append(clean(f"Helpful files look like {nl_join(file_patterns[:3])}"))
        elif hints:
            tips.append(clean(f"Useful examples include {nl_join(hints[:3])}"))
        else:
            tips.append('Include a direct artefact that shows the work you did')

        tips.append('When you upload give each file a short title and date and add a one line note saying what the item shows and when it happened')

        # Permission note for external stakeholders
        perm = ''
        if any(word in lc for word in ['outside', 'ngo', 'community', 'school', 'stakeholder', 'municipal']):
            perm = 'For stakeholders outside NWU you may need goodwill permission or a memorandum of understanding before access'
        else:
            perm = 'If formal documents are not available add a dated confirmation email or a short colleague statement and mark it as supplementary'
        tips.append(clean(perm))

        # Value line or KPA snippet if available
        insert_lines: List[str] = []
        try:
            vpath = Path(__file__).resolve().parent / 'data' / 'nwu_brain' / 'values_index.json'
            corpus = ' '.join([title or '', kpa or '', ' '.join(examples or []), ' '.join(labels or []), ' '.join(preferred_examples or [])]).lower()
            best_value = None
            best_score = 0.0
            if vpath.exists():
                vdata = json.loads(vpath.read_text(encoding='utf-8'))
                # quick heuristic by KPA name to avoid obvious mismatches
                kpa_lc = (kpa or '').lower()
                if kpa_lc:
                    if 'social' in kpa_lc or 'community' in kpa_lc or 'engagement' in kpa_lc:
                        best_value = 'Social Responsiveness'
                    elif 'teach' in kpa_lc or 'learn' in kpa_lc or 'curriculum' in kpa_lc:
                        best_value = 'Lifelong Learning'
                    elif 'research' in kpa_lc or 'innovation' in kpa_lc:
                        best_value = 'Innovation'
                    elif 'safety' in kpa_lc or 'ohs' in kpa_lc:
                        best_value = 'Accountability'
                # if heuristic did not decide, fall back to keyword scoring
                if not best_value:
                    for v in vdata.get('core_values', []):
                        score = 0.0
                        for kw in v.get('keywords', []):
                            pattern = kw.get('pattern') or ''
                            weight = float(kw.get('weight') or 1.0)
                            try:
                                if pattern and re.search(pattern, corpus):
                                    score += weight
                            except re.error:
                                if pattern and pattern in corpus:
                                    score += weight
                        if score > best_score:
                            best_score = score
                            best_value = v.get('name')
            if best_value:
                insert_lines.append(clean(f'This activity reflects the NWU value {best_value} and demonstrates community engagement and social impact'))
        except Exception:
            pass

        try:
            gpath = Path(__file__).resolve().parent / 'data' / 'nwu_brain' / 'kpa_guidelines.md'
            if gpath.exists() and kpa:
                md = gpath.read_text(encoding='utf-8')
                marker = '## ' + kpa.split(':')[0] if ':' in kpa else '## ' + kpa
                if marker not in md:
                    marker = '## KPA5' if '5' in (kpa or '') or 'social' in (kpa or '').lower() else marker
                if marker in md:
                    start = md.index(marker)
                    rest = md[start:]
                    end = rest.find('\n---')
                    snippet = rest if end==-1 else rest[:end]
                    if 'Accepted Evidence' in snippet:
                        ae_idx = snippet.find('Accepted Evidence')
                        ae = snippet[ae_idx:]
                        lines = [ln.strip('- * ') for ln in ae.splitlines() if ln.strip().startswith('-')][:5]
                        if lines:
                            insert_lines.append(clean('Accepted evidence commonly includes ' + ', '.join(lines)))
        except Exception:
            pass

        parts = []
        if opener:
            parts.append(clean(opener))
        parts.append(summary)
        parts.extend(insert_lines)
        parts.extend(tips)

        # Join into readable sentences
        text = '. '.join([p for p in parts if p])
        text = text.replace(':', '').replace('-', ' ').replace('–', ' ').replace('—', ' ').replace('"', '').replace("'", '').replace('*', '')
        text = ' '.join(text.split())
        return {"template_id": "_generated_qualitative_short", "source": "generated", "text": text}

    # Build a personal, rigorous guidance narrative (detailed fallback)
    lines: List[str] = []
    lines.append(f"Hi — for '{title}' (KPA: {kpa}).")
    lines.append(f"This task is scheduled for {month or 'the stated month'}. The clear requirement is {min_req} primary artefact{'s' if min_req!=1 else ''}.")

    # Evidence specifics using taxonomy where available
    if evidence_required:
        lines.append(f"Explicit requirement: {evidence_required}.")
    if preferred_examples:
        ex_sample = ', '.join(preferred_examples[:5])
        lines.append(f"Most persuasive items for this KPA are: {ex_sample}.")
    elif hints:
        lines.append(f"Useful examples: {', '.join(hints[:5])}.")

    # Practical upload instructions — personal tone, no punctuation names
    upload_lines: List[str] = []
    upload_lines.append(f"I recommend you upload primary item(s) that directly show the outcome, and add supporting items as needed.")
    upload_lines.append("Label each file with a short title and date, and add a one-line note explaining how it demonstrates the outcome. For example: Agenda chaired meeting on 2025-01-15.")

    # Heuristic ordering based on keywords and taxonomy
    if 'curriculum' in title.lower() or any('curriculum' in e.lower() for e in preferred_examples):
        upload_lines.append("Preferred primary items: curriculum or module document with your name or role, assessment rubrics, LMS exports showing content published.")
    elif 'committee' in title.lower() or any('committee' in e.lower() for e in preferred_examples):
        upload_lines.append("Preferred primary items: meeting invite or calendar entry with your name, agenda or minutes noting your role, and follow-up emails confirming decisions.")
    elif 'teach' in kpa.lower() or 'teaching' in kpa.lower() or 'lesson' in title.lower():
        upload_lines.append("Preferred primary items: lesson plan with dates, slide deck used in class, and a short student feedback excerpt or LMS activity screenshot.")
    else:
        upload_lines.append("Preferred primary items: a direct artefact showing the activity, a corroborating artefact such as an email or register, and a short reflective note.")

    # Practical fallback when documents missing
    upload_lines.append("If formal documents are unavailable, upload a dated email confirmation or a short signed statement from a colleague and explain briefly.")

    # Quality checklist, personal tone
    checklist = (
        "Quality checklist: make sure each primary item names you or shows your role; dates are visible; filenames include task name and month; include a short note linking the artefact to the outcome."
    )

    lines.extend(upload_lines)
    lines.append(checklist)

    text = "\n\n".join(lines)
    return {"template_id": "_generated_qualitative", "source": "generated", "text": text}
