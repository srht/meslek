"""Geçiş önerisi puanlaması.

Her aday pozisyon için dört alt skor hesaplanır ve ağırlıklı toplanır:
  - örtüşme   : mevcut becerilerin pozisyonun gereksinimlerini ne kadar karşıladığı
  - hazırlık  : eksik temel becerileri kapatmak için gereken tahmini süre (ters)
  - talep     : ilan hacmi ve eğilimi
  - fırsat    : ilan başına düşen aday (az rekabet = yüksek fırsat)

Beceri sahibi olunmasa bile grafın RELATED_TO kenarları üzerinden kısmi
aktarım kredisi verilir (ör. Java -> Apex).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from .graph import Role, SkillGraph

LEVEL_CREDIT = {1: 0.5, 2: 0.8, 3: 1.0}
LEVEL_NAMES = {1: "temel", 2: "orta", 3: "ileri"}
# Komşu beceriden gelen aktarım, doğrudan bilgiye göre indirimli sayılır.
TRANSFER_DAMPING = 0.6
# Bu kadar haftalık eksik, hazırlık skorunu sıfırlar.
MAX_GAP_WEEKS = 40.0

WEIGHTS = {"overlap": 0.40, "readiness": 0.25, "demand": 0.20, "opportunity": 0.15}


@dataclass
class SkillMatch:
    skill_id: str
    name: str
    essential: bool
    credit: float
    via: str | None  # kredinin geldiği beceri (doğrudan ise kendisi, aktarımsa komşu)
    weeks_to_learn: float


@dataclass
class Recommendation:
    role_id: str
    title: str
    kind: str
    product: str | None
    score: float
    overlap: float
    readiness: float
    demand: float
    opportunity: float
    gap_weeks: float
    ready: bool  # tüm temel becerilere doğrudan sahip
    postings_90d: int
    trend: float
    candidates_per_posting: float
    matched: list[SkillMatch]
    transferred: list[SkillMatch]
    missing: list[SkillMatch]
    reasons: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _credit(graph: SkillGraph, person: dict[str, int], skill_id: str) -> tuple[float, str | None]:
    if skill_id in person:
        return LEVEL_CREDIT[person[skill_id]], skill_id
    best, via = 0.0, None
    for neighbor, sim in graph.neighbors(skill_id).items():
        if neighbor in person:
            c = sim * LEVEL_CREDIT[person[neighbor]] * TRANSFER_DAMPING
            if c > best:
                best, via = c, neighbor
    return best, via


def _market_normalizers(graph: SkillGraph) -> tuple[float, float]:
    max_postings = max(r.market.postings_90d for r in graph.roles.values())
    max_ratio = max(_ratio(r) for r in graph.roles.values())
    return math.log1p(max_postings), math.log1p(max_ratio)


def _ratio(role: Role) -> float:
    """İlan / aday oranı, x100 (log ölçek için)."""
    return 100 * role.market.postings_90d / max(role.market.candidates, 1)


def score_role(graph: SkillGraph, person: dict[str, int], role: Role) -> Recommendation:
    total_w = sum(r.weight for r in role.requirements)
    got_w = 0.0
    gap_weeks = 0.0
    matched, transferred, missing = [], [], []

    for req in role.requirements:
        skill = graph.skills[req.skill_id]
        credit, via = _credit(graph, person, req.skill_id)
        got_w += req.weight * credit
        weeks = round(skill.learn_weeks * (1 - credit), 1)
        if req.essential:
            gap_weeks += weeks
        m = SkillMatch(req.skill_id, skill.name, req.essential, round(credit, 2), via, weeks)
        if via == req.skill_id:
            matched.append(m)
        elif via is not None:
            transferred.append(m)
            if req.essential:
                missing.append(m)
        elif req.essential or credit == 0:
            missing.append(m)

    overlap = got_w / total_w if total_w else 0.0
    readiness = 1 - min(gap_weeks / MAX_GAP_WEEKS, 1.0)

    log_max_postings, log_max_ratio = _market_normalizers(graph)
    mk = role.market
    demand = math.log1p(mk.postings_90d) / log_max_postings
    demand = max(0.0, min(1.0, demand * (1 + mk.trend)))
    opportunity = math.log1p(_ratio(role)) / log_max_ratio

    score = (
        WEIGHTS["overlap"] * overlap
        + WEIGHTS["readiness"] * readiness
        + WEIGHTS["demand"] * demand
        + WEIGHTS["opportunity"] * opportunity
    )

    missing.sort(key=lambda m: (not m.essential, -m.weeks_to_learn))
    rec = Recommendation(
        role_id=role.id,
        title=role.title,
        kind=role.kind,
        product=role.product,
        score=round(score, 3),
        overlap=round(overlap, 3),
        readiness=round(readiness, 3),
        demand=round(demand, 3),
        opportunity=round(opportunity, 3),
        gap_weeks=round(gap_weeks, 1),
        ready=not any(m.essential for m in missing),
        postings_90d=mk.postings_90d,
        trend=mk.trend,
        candidates_per_posting=round(mk.candidates / max(mk.postings_90d, 1), 1),
        matched=matched,
        transferred=transferred,
        missing=missing,
        reasons=[],
    )
    rec.reasons = _reasons(graph, rec)
    return rec


def _reasons(graph: SkillGraph, rec: Recommendation) -> list[str]:
    reasons = [
        f"Bu pozisyon için son 90 günde {rec.postings_90d} ilan var"
        + (f" (yıllık eğilim %{rec.trend * 100:+.0f})." if rec.trend else "."),
        f"Becerilerinin pozisyon gereksinimleriyle örtüşmesi %{rec.overlap * 100:.0f}.",
    ]
    for t in rec.transferred[:2]:
        src = graph.skills[t.via].name
        reasons.append(f"{src} bilgin {t.name} öğrenmeyi kolaylaştırır (%{t.credit * 100:.0f} aktarım).")
    essential_missing = [m for m in rec.missing if m.essential and m.weeks_to_learn > 0]
    if essential_missing:
        names = ", ".join(m.name for m in essential_missing[:3])
        reasons.append(f"Eksik temel beceriler: {names} — tahmini ~{rec.gap_weeks:.0f} hafta.")
    elif rec.gap_weeks > 0:
        reasons.append(f"Temel beceriler mevcut; seviyeyi derinleştirmek ~{rec.gap_weeks:.0f} hafta sürer.")
    else:
        reasons.append("Temel becerilerin tamamı karşılanıyor; doğrudan başvurabilirsin.")
    reasons.append(f"İlan başına yaklaşık {rec.candidates_per_posting:g} aday düşüyor.")
    return reasons


def recommend(
    graph: SkillGraph,
    person: dict[str, int],
    limit: int = 5,
    include_ready: bool = True,
) -> list[Recommendation]:
    """Kişinin becerilerine göre pozisyonları sıralar.

    person: {skill_id: seviye(1-3)}. Bilinmeyen beceriler yok sayılır.
    include_ready=False ise temel becerilerin hepsine zaten sahip olunan
    (muhtemelen mevcut) pozisyonlar elenir.
    """
    person = {k: _clamp_level(v) for k, v in person.items() if k in graph.skills}
    if not person:
        return []
    recs = [score_role(graph, person, role) for role in graph.roles.values()]
    recs = [r for r in recs if r.overlap > 0]
    if not include_ready:
        recs = [r for r in recs if not r.ready]
    recs.sort(key=lambda r: r.score, reverse=True)
    return recs[:limit]


def _clamp_level(level: int) -> int:
    return max(1, min(3, int(level)))
