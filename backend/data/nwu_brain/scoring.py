#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nwu_brain/scoring.py  —  Canonical, deterministic scorer for the NWU Brain

Public API
----------
scorer = NWUScorer(<path_to>/nwu_brain/brain_manifest.json)

scored   = scorer.compute(item_dict)     # → canonical scored dict
csv_row  = scorer.to_csv_row(scored)     # → flat CSV v2 row (for exports)
modeljs  = scorer.to_model_json(scored)  # → compact structure for assistant prompts

Design notes
------------
• BOM-tolerant JSON loader
• Manifest-first: every file is resolved from brain_manifest.json ("files" map)
• Deterministic:
    - KPA routing via kpa_router.json (by extension/platform/regex)
    - Clause matches via clause_packs.json + policy_registry.json
    - Values signal via values_index.json
    - Tier via tier_keywords.json (first-match precedence; tolerant to several shapes)
    - Band via institution_profile.json thresholds (fallback defaults provided)
• Conservative defaults: scorer degrades gracefully; never crashes your pipeline
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


# -----------------------
# Low-level file utilities
# -----------------------

_JSON_RE_FLAGS = re.IGNORECASE | re.MULTILINE | re.DOTALL


def _read_text(path: Path) -> str:
    b = path.read_bytes()
    # Strip UTF BOM if present
    if b[:3] == b"\xef\xbb\xbf":
        b = b[3:]
    return b.decode("utf-8", errors="ignore")


def _read_json(path: Path) -> Any:
    return json.loads(_read_text(path))


def _compile_pat(pat: str, flags: int = _JSON_RE_FLAGS) -> re.Pattern:
    try:
        return re.compile(pat, flags)
    except re.error:
        # Very tolerant fallback: escape the pattern if it's broken
        return re.compile(re.escape(pat), flags)


# -----------------------
# Data carriers
# -----------------------

@dataclass
class BandRule:
    name: str
    min_score: float  # inclusive lower bound on 0..5 scale


# -----------------------
# NWUScorer (public)
# -----------------------

class NWUScorer:
    """
    Canonical scorer wired to brain_manifest.json
    """
    def __init__(self, brain_manifest_path: str | Path):
        self.manifest_path = Path(brain_manifest_path).resolve()
        if not self.manifest_path.is_file():
            raise FileNotFoundError(f"brain_manifest.json not found: {self.manifest_path}")

        manifest = _read_json(self.manifest_path)
        if not isinstance(manifest, dict) or "files" not in manifest:
            raise ValueError("Invalid brain_manifest.json (missing 'files')")

        self.base_dir = self.manifest_path.parent
        self.files_map: Dict[str, str] = manifest.get("files", {}) or {}

        # Resolve required files (errors are explicit; optional ones are tolerated)
        def _fp(key: str) -> Path:
            rel = self.files_map.get(key)
            if not rel:
                raise FileNotFoundError(f"Manifest missing file key: {key}")
            return (self.base_dir / rel).resolve()

        # Core knowledge files
        self.policy_registry_path      = _fp("policy_registry.json")
        self.clause_packs_path         = _fp("clause_packs.json")
        self.kpa_router_path           = _fp("kpa_router.json")
        self.tier_keywords_path        = _fp("tier_keywords.json")
        self.values_index_path         = _fp("values_index.json")
        self.institution_profile_path  = _fp("institution_profile.json")

        # Optional map (debug)
        self.policy_id_map_path = (self.base_dir / self.files_map["policy_id_map.json"]).resolve() \
                                  if self.files_map.get("policy_id_map.json") else None

        # Load all JSONs
        self.policy_registry: Dict[str, Dict[str, Any]] = _read_json(self.policy_registry_path)
        self.clause_packs: Dict[str, Dict[str, Any]]    = _read_json(self.clause_packs_path)
        self.kpa_router: Dict[str, Any]                 = _read_json(self.kpa_router_path)
        self.tier_keywords_raw: Any                     = _read_json(self.tier_keywords_path)
        self.values_index: Dict[str, Any]               = _read_json(self.values_index_path)
        self.institution_profile: Dict[str, Any]        = _read_json(self.institution_profile_path)

        # Pre-compile clause regexes per policy for speed & determinism
        self._compiled_clauses: Dict[str, List[Tuple[str, re.Pattern]]] = {}
        for pol_id, pack in self.clause_packs.items():
            patterns = []
            for clause in pack.get("clauses", []):
                code = str(clause.get("code") or f"{pol_id}::clause")
                pat  = str(clause.get("pattern") or "")
                if not pat:
                    continue
                patterns.append((code, _compile_pat(pat)))
            self._compiled_clauses[pol_id] = patterns

        # Prepare tier regex lists (TOLERANT to dict|list|string)
        self._compiled_tiers: List[Tuple[str, List[re.Pattern]]] = self._prepare_tiers(self.tier_keywords_raw)

        # Build band thresholds (defaults if not present)
        self.bands: List[BandRule] = self._load_bands(self.institution_profile)

    # -----------------------
    # Public entrypoint
    # -----------------------
    def compute(self, item: dict | None = None, **kwargs) -> dict:
        """
        Deterministic scoring entrypoint.
        Accepts a single dict (preferred) or kwargs (fallback).
        Returns a canonical scored object with fields consumed by CSV/assistant.

        Expected item keys (best-effort; scorer is tolerant):
            title, path, relpath, platform|source, modified, size, hash, full_text
        """
        if item is None:
            item = kwargs
        if not isinstance(item, dict):
            raise TypeError("NWUScorer.compute() expects a dict or kwargs")

        title     = _coerce_str(item.get("title") or item.get("name") or item.get("path") or "")
        platform  = _coerce_str(item.get("platform") or item.get("source") or "")
        full_text = _coerce_str(item.get("full_text") or "")
        relpath   = _coerce_str(item.get("relpath") or "")
        modified  = _coerce_str(item.get("modified") or item.get("date") or "")
        size      = item.get("size")
        sha1      = _coerce_str(item.get("hash") or "")

        # 1) Route KPA deterministically
        kpa_list = self._route_kpa(title=title, platform=platform, path=item.get("path") or "", text=full_text)

        # 2) Tier detection (first-match precedence)
        tier_name, tier_rule = self._derive_tier(full_text, title)

        # 3) Values index signal
        values_score, values_hits = self._score_values(full_text)

        # 4) Policy matching (canonical)
        policy_hits, policy_hit_details = self._match_policies(full_text, title)

        # 5) Must-pass risks (conservative default: empty; see note)
        must_pass_risks: List[Dict[str, Any]] = []

        # 6) Numeric score (0..5) → band
        score = self._compose_score(values_score, tier_name, len(policy_hits))
        band  = self._to_band(score)

        # 7) Minimal rationales/actions (seeded; backend/assistant can expand)
        rationale = self._mk_rationale(kpa_list, tier_name, values_hits, policy_hits)
        actions   = self._mk_actions(kpa_list, tier_name, policy_hits, values_hits)

        # Canonical object (keep names stable)
        out = {
            # Context passthrough (safe fields only)
            "title": title, "platform": platform, "relpath": relpath,
            "modified": modified, "size": size, "hash": sha1,

            # Deterministic NWU Brain fields
            "kpa": kpa_list,                               # List[int]
            "tier": [tier_name] if tier_name else [],      # List[str]
            "tier_rule": tier_rule,                        # str
            "values_score": round(values_score, 3),
            "values_hits": values_hits,                    # List[str]
            "policy_hits": policy_hits,                    # List[dict]
            "policy_hit_details": policy_hit_details,      # List[str]
            "must_pass_risks": must_pass_risks,            # List[dict]
            "score": round(score, 3),                      # 0..5
            "band": band,                                  # str
            "rationale": rationale,                        # str
            "actions": actions,                            # List[str]
        }
        return out

    # -----------------------
    # CSV v2 rendering
    # -----------------------
    def to_csv_row(self, scored: Dict[str, Any]) -> Dict[str, Any]:
        """
        Return a flattened row with expected columns for CSV v2 writer.
        Do NOT include 'full_text' here.
        """
        return {
            "kpa": scored.get("kpa", []),
            "tier": scored.get("tier", []),
            "tier_rule": scored.get("tier_rule", ""),
            "values_score": scored.get("values_score", 0.0),
            "values_hits": scored.get("values_hits", []),
            "policy_hits": scored.get("policy_hits", []),
            "policy_hit_details": scored.get("policy_hit_details", []),
            "must_pass_risks": scored.get("must_pass_risks", []),
            "score": scored.get("score", 0.0),
            "band": scored.get("band", ""),
            "rationale": scored.get("rationale", ""),
            "actions": scored.get("actions", []),
        }

    # -----------------------
    # Assistant model JSON
    # -----------------------
    def to_model_json(self, scored: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compact structure for LLM prompts (strict system_nwu.txt expects this shape).
        """
        return {
            "kpa": scored.get("kpa") or [],
            "tier": scored.get("tier") or [],
            "score": float(scored.get("score") or 0.0),
            "band": scored.get("band") or "",
            "values": {
                "score": float(scored.get("values_score") or 0.0),
                "hits": scored.get("values_hits") or [],
            },
            "policies": [
                {
                    "id": h.get("id"),
                    "code": h.get("code"),
                    "severity": h.get("severity"),
                    "excerpt": h.get("excerpt"),
                } for h in (scored.get("policy_hits") or [])
            ],
            "policy_hit_details": scored.get("policy_hit_details") or [],
            "must_pass_risks": scored.get("must_pass_risks") or [],
            "rationale": scored.get("rationale") or "",
            "actions": scored.get("actions") or [],
            "context": {
                "title": scored.get("title") or "",
                "platform": scored.get("platform") or "",
                "relpath": scored.get("relpath") or "",
                "modified": scored.get("modified") or "",
                "hash": scored.get("hash") or "",
            }
        }

    # =======================
    # Internal helper methods
    # =======================

    # --- Bands ---
    def _load_bands(self, prof: Dict[str, Any]) -> List[BandRule]:
        """
        Expect either:
          {"bands":[{"name":"Unsatisfactory","min":0.0}, ... ]}
        or derive conservative defaults if not present.
        """
        bands_cfg = []
        if isinstance(prof, dict):
            bands_cfg = prof.get("bands") or prof.get("score_bands") or []
        rules: List[BandRule] = []
        if isinstance(bands_cfg, list) and bands_cfg:
            for b in bands_cfg:
                try:
                    rules.append(BandRule(name=str(b["name"]), min_score=float(b["min"])))
                except Exception:
                    continue
            # order by min_score descending (so first match wins)
            rules.sort(key=lambda x: x.min_score, reverse=True)
            return rules
        # Fallback defaults (0..5 scale)
        return [
            BandRule("Excellent", 4.5),
            BandRule("Proficient", 3.5),
            BandRule("Competent", 2.5),
            BandRule("Developing", 1.5),
            BandRule("Unsatisfactory", 0.0),
        ]

    def _to_band(self, score_0_to_5: float) -> str:
        s = float(score_0_to_5)
        for rule in self.bands:
            if s >= rule.min_score:
                return rule.name
        return self.bands[-1].name if self.bands else ""

    # --- Tiers ---
    def _prepare_tiers(self, raw: Any) -> List[Tuple[str, List[re.Pattern]]]:
        """
        Accepts a variety of shapes for tier_keywords.json while preserving order:

        1) Dict[str, Any]                           {"Gold": {"patterns":[...]}, "Silver": [...]}
        2) List[{"name":..., "patterns":[...]}]     [{"name":"Gold","patterns":[...]}, ...]
        3) List[{"tier":..., "patterns":[...]}]     [{"tier":"Gold","patterns":[...]}, ...]
        4) List[{"Gold":[...]}] / [{"Gold":{"patterns":[...]}}]
        5) Dict[str, List[str]]                     {"Gold":[...], "Silver":[...]}
        6) Dict[str, str]                           {"Gold":"regex", ...}
        7) List[str]                                ["regex1", "regex2"]  → treated as single tier "Tier"

        Returns list of (tier_name, [compiled_patterns]) in precedence order.
        """
        out: List[Tuple[str, List[re.Pattern]]] = []

        if isinstance(raw, dict):
            # preserve insertion order
            for tier_name, spec in raw.items():
                pats: List[str] = []
                if isinstance(spec, dict):
                    src = spec.get("patterns", spec)
                    if isinstance(src, dict):
                        src = list(src.values())
                    if isinstance(src, list):
                        pats = [str(x) for x in src if x]
                    elif isinstance(src, str):
                        pats = [src]
                elif isinstance(spec, list):
                    pats = [str(x) for x in spec if x]
                elif isinstance(spec, str):
                    pats = [spec]
                comp = [_compile_pat(p) for p in pats if p]
                out.append((str(tier_name), comp))
            return out

        if isinstance(raw, list):
            # Could be list of dicts, list of strings, or list of {"Tier":[...]} dicts
            # 7) List[str] → single tier "Tier"
            if all(isinstance(x, str) for x in raw):
                comp = [_compile_pat(str(p)) for p in raw if p]
                out.append(("Tier", comp))
                return out

            for item in raw:
                if isinstance(item, dict):
                    # 2) {"name":..., "patterns":[...]} or 3) {"tier":..., "patterns":[...]}
                    name = item.get("name") or item.get("tier")
                    if name:
                        src = item.get("patterns", item)
                        if isinstance(src, dict):
                            src = list(src.values())
                        if isinstance(src, list):
                            pats = [str(x) for x in src if x]
                        elif isinstance(src, str):
                            pats = [src]
                        else:
                            pats = []
                        comp = [_compile_pat(p) for p in pats if p]
                        out.append((str(name), comp))
                        continue
                    # 4) {"Gold":[...]} / {"Gold":{"patterns":[...]}}
                    if len(item) == 1:
                        (k, v), = item.items()
                        pats: List[str] = []
                        if isinstance(v, dict):
                            src = v.get("patterns", v)
                            if isinstance(src, dict):
                                src = list(src.values())
                            if isinstance(src, list):
                                pats = [str(x) for x in src if x]
                            elif isinstance(src, str):
                                pats = [src]
                        elif isinstance(v, list):
                            pats = [str(x) for x in v if x]
                        elif isinstance(v, str):
                            pats = [v]
                        comp = [_compile_pat(p) for p in pats if p]
                        out.append((str(k), comp))
                        continue
                # ignore unknown shapes silently
            return out

        # Unknown shape → no tiers
        return out

    def _derive_tier(self, text: str, title: str) -> Tuple[str, str]:
        """
        First tier whose patterns match text/title wins.
        Returns (tier_name, rule_name)
        """
        hay = f"{title}\n{text}" if text else title
        for tier_name, pats in self._compiled_tiers:
            for p in pats:
                if p.search(hay):
                    return tier_name, tier_name
        return "", ""

    # --- KPA routing ---
    def _route_kpa(self, title: str, platform: str, path: str, text: str) -> List[int]:
        """
        Deterministic routing based on kpa_router.json:
          {
            "by_extension": {"pdf":[1,3], "docx":[1], ...},
            "by_platform": {"Outlook":[1,4], "GoogleDrive":[3], ...},
            "by_regex": [{"pattern":"assessment|moderation","kpa":[1,4]}, ...]
          }
        Returns de-duplicated, sorted list of KPA ints in 1..5
        """
        out: List[int] = []
        r = self.kpa_router or {}
        # 1) extension
        ext = _ext_of(title) or _ext_of(path)
        if ext and "by_extension" in r:
            out.extend(_as_kpa_list(r["by_extension"].get(ext, [])))

        # 2) platform
        plat_key = (platform or "").strip()
        if plat_key and "by_platform" in r:
            out.extend(_as_kpa_list(r["by_platform"].get(plat_key, [])))

        # 3) regex content/title
        if "by_regex" in r and (text or title):
            hay = f"{title}\n{text}" if text else title
            for rule in (r["by_regex"] or []):
                pat = str(rule.get("pattern") or "")
                if not pat:
                    continue
                if _compile_pat(pat).search(hay):
                    out.extend(_as_kpa_list(rule.get("kpa", [])))

        # Dedup + sanitize
        out_uni = sorted({k for k in out if isinstance(k, int) and 1 <= k <= 5})
        return out_uni

    # --- Values index ---
    def _score_values(self, text: str) -> Tuple[float, List[str]]:
        """
        Very fast values hit counter. Expected structure:
          values_index.json: {"values": [{"name":"Integrity","patterns":[...]}, ...]}
        Score is a squashed transform into 0..5.
        """
        hits: List[str] = []
        spec = self.values_index or {}
        arr = spec.get("values") if isinstance(spec, dict) else None
        if not isinstance(arr, list):
            return 0.0, hits

        total_hits = 0
        for v in arr:
            name = str(v.get("name") or "").strip()
            pats = v.get("patterns") or []
            count_for_value = 0
            for pat in pats:
                if not pat:
                    continue
                m = len(list(_compile_pat(str(pat)).finditer(text)))
                count_for_value += m
            if count_for_value > 0 and name:
                hits.append(name)
                total_hits += min(count_for_value, 5)  # cap per value to avoid runaway counts

        # Smooth scale: 0 hits → 0.0, many hits → asymptote near 5.0
        score = 5.0 * (1.0 - math.exp(-0.15 * total_hits))
        return score, hits

    # --- Policy matching ---
    def _match_policies(self, text: str, title: str) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Loop through clause packs; collect hits with excerpts. Canonical IDs only.
        Returns (policy_hits, policy_hit_details)
        """
        policy_hits: List[Dict[str, Any]] = []
        details: List[str] = []
        hay = f"{title}\n{text}" if text else title

        for pol_id, patterns in self._compiled_clauses.items():
            for code, regex in patterns:
                m = regex.search(hay)
                if not m:
                    continue
                # Extract small excerpt around the match
                span = m.span()
                excerpt = _snippet(hay, span[0], span[1], 120)
                meta = self.policy_registry.get(pol_id, {})
                policy_hits.append({
                    "id": pol_id,
                    "code": code,
                    "severity": meta.get("severity") or "",
                    "excerpt": excerpt,
                })
                details.append(f"{pol_id}:{code} → {excerpt}")
        return policy_hits, details

    # --- Composite score ---
    def _compose_score(self, values_score: float, tier_name: str, policy_count: int) -> float:
        """
        Compose 0..5 score deterministically. Transparent and easy to tune.
        """
        tier_weight = {
            "Platinum": 2.0,
            "Gold": 1.6,
            "Silver": 1.2,
            "Bronze": 0.8,
            "Base": 0.4,
            "": 0.0,
        }.get(tier_name, 0.0)

        # Policy signal: diminishing returns
        pol_signal = 1.6 * (1.0 - math.exp(-0.35 * max(0, policy_count)))

        base = 0.6  # small bias so non-empty artefacts don't flatline at 0
        score = base + (0.55 * (values_score / 5.0) * 5.0) + tier_weight + pol_signal
        return max(0.0, min(5.0, score))

    # --- Rationale/actions (succinct seed text) ---
    def _mk_rationale(self, kpa: List[int], tier: str, values_hits: List[str], policy_hits: List[Dict[str, Any]]) -> str:
        parts = []
        if kpa:
            parts.append(f"KPA: {', '.join(f'KPA{n}' for n in kpa)}")
        if tier:
            parts.append(f"Tier: {tier}")
        if values_hits:
            parts.append(f"Values: {', '.join(values_hits[:4])}")
        if policy_hits:
            pol_ids = sorted({h.get("id") for h in policy_hits if h.get("id")})
            parts.append(f"Policies: {', '.join(pol_ids[:6])}")
        return " | ".join(parts) if parts else "No strong matches; basic evidence recorded."

    def _mk_actions(self, kpa: List[int], tier: str, policy_hits: List[Dict[str, Any]], values_hits: List[str]) -> List[str]:
        acts: List[str] = []
        if not kpa:
            acts.append("Clarify KPA context in filename or cover note for deterministic routing.")
        if not policy_hits:
            acts.append("Include explicit policy phrases or annex references to strengthen traceability.")
        if not values_hits:
            acts.append("Add reflective statements that evidence institutional values in practice.")
        if not tier:
            acts.append("Map this artefact to a tier using the tier rubric; add keywords in the cover page.")
        return acts[:5]


# ---------------
# Tiny helpers
# ---------------

def _coerce_str(x: Any) -> str:
    if x is None:
        return ""
    return str(x)


def _ext_of(name: str | Any) -> str:
    try:
        s = (name or "").lower()
        if "." in s:
            return s.rsplit(".", 1)[-1]
    except Exception:
        pass
    return ""


def _as_kpa_list(v: Any) -> List[int]:
    out: List[int] = []
    if isinstance(v, list):
        for x in v:
            try:
                n = int(x)
                if 1 <= n <= 5:
                    out.append(n)
            except Exception:
                continue
    elif isinstance(v, (int, float)) and 1 <= int(v) <= 5:
        out.append(int(v))
    return out


def _snippet(hay: str, a: int, b: int, radius: int = 100) -> str:
    a0 = max(0, a - radius)
    b0 = min(len(hay), b + radius)
    snip = hay[a0:b0].strip()
    # compact whitespace
    snip = re.sub(r"\s+", " ", snip)
    return snip[:240]
