from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DATA_PATH = Path(__file__).resolve().parent / "data" / "nwu_people_index.json"


ROLE_TIERS: list[tuple[str, str, float]] = [
    ("dean", "A", 0.20),
    ("director", "A", 0.20),
    ("deputy director", "A", 0.20),
    ("subject group", "A", 0.18),
    ("chair", "A", 0.18),
    ("personal assistant", "A", 0.16),
    ("administrator", "A", 0.16),
    ("admin", "A", 0.16),
    ("professor", "B", 0.12),
    ("associate professor", "B", 0.12),
    ("senior lecturer", "B", 0.10),
    ("lecturer", "B", 0.08),
    ("colleague", "B", 0.08),
    ("student", "C", 0.03),
]


@dataclass(frozen=True)
class PeopleMatch:
    name: str
    email: str
    role: str
    unit: str
    tier: str
    confidence_boost: float
    matched_on: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "email": self.email,
            "role": self.role,
            "unit": self.unit,
            "tier": self.tier,
            "confidence_boost": self.confidence_boost,
            "matched_on": self.matched_on,
        }


def _normalize(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def _tokenize_person_name(name: str) -> set[str]:
    parts = {
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", name or "")
        if token.lower() not in {"dr", "prof", "mr", "mrs", "ms", "miss"}
    }
    return parts


def _role_tier(role: str) -> tuple[str, float]:
    role_l = role.lower()
    for marker, tier, boost in ROLE_TIERS:
        if marker in role_l:
            return tier, boost
    return "C", 0.04


def load_people_index(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or DATA_PATH
    if not target.exists():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return []
    people = data.get("people") if isinstance(data, dict) else data
    if not isinstance(people, list):
        return []
    return [item for item in people if isinstance(item, dict)]


def match_people(
    text: str,
    *,
    people: list[dict[str, Any]] | None = None,
    max_matches: int = 4,
) -> list[PeopleMatch]:
    """Match known NWU people against sender/body text.

    The index intentionally uses public staff/role data only. Matching is
    conservative: email address is strongest; otherwise require at least two
    name tokens or an explicit alias.
    """
    text_norm = _normalize(text)
    text_l = text_norm.lower()
    people = people if people is not None else load_people_index()

    matches: list[tuple[float, PeopleMatch]] = []
    for person in people:
        name = _normalize(person.get("name"))
        email = _normalize(person.get("email")).lower()
        role = _normalize(person.get("role"))
        unit = _normalize(person.get("unit"))
        aliases = [_normalize(a) for a in person.get("aliases", []) if _normalize(a)]
        tier, boost = _role_tier(role)

        score = 0.0
        matched_on = ""
        if email and email in text_l:
            score = 3.0
            matched_on = "email"
        else:
            for alias in aliases:
                if alias and re.search(rf"\b{re.escape(alias.lower())}\b", text_l):
                    score = max(score, 2.0)
                    matched_on = f"alias:{alias}"
            tokens = _tokenize_person_name(name)
            if len(tokens) >= 2:
                hits = [tok for tok in tokens if re.search(rf"\b{re.escape(tok)}\b", text_l)]
                if len(hits) >= 2:
                    score = max(score, 1.5 + (0.1 * len(hits)))
                    matched_on = "name"

        if score <= 0:
            continue

        matches.append(
            (
                score + boost,
                PeopleMatch(
                    name=name,
                    email=email,
                    role=role,
                    unit=unit,
                    tier=tier,
                    confidence_boost=boost,
                    matched_on=matched_on,
                ),
            )
        )

    matches.sort(key=lambda item: item[0], reverse=True)
    deduped: list[PeopleMatch] = []
    seen: set[str] = set()
    for _, match in matches:
        marker = match.email or match.name.lower()
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(match)
        if len(deduped) >= max_matches:
            break
    return deduped


def source_context_for_text(text: str, *, source: str = "") -> dict[str, Any]:
    people_matches = match_people(text)
    top = people_matches[0] if people_matches else None
    source_l = (source or "").lower()

    system_tier = ""
    system_reason = ""
    if "efundi" in text.lower() or "efundi" in source_l:
        system_tier = "A"
        system_reason = "eFundi/LMS source signal"
    elif "calendar" in source_l:
        system_tier = "A"
        system_reason = "Outlook calendar appointment"

    tier = system_tier or (top.tier if top else "C")
    boost = max([top.confidence_boost if top else 0.0, 0.18 if system_tier == "A" else 0.0])
    reasons = []
    if system_reason:
        reasons.append(system_reason)
    if top:
        reasons.append(f"matched NWU person: {top.name} ({top.role})")

    return {
        "source_trust_tier": tier,
        "confidence_boost": boost,
        "reasons": reasons,
        "people_matches": [match.as_dict() for match in people_matches],
    }
