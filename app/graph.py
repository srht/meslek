"""Meslek–beceri grafı.

Düğüm tipleri:
  - Skill  (beceri; ürün uzmanlıkları da beceri düğümüdür, category="ürün")
  - Role   (pozisyon)

Kenar tipleri:
  - Role  -[REQUIRES {weight}]-> Skill    (temel / isteğe bağlı)
  - Skill -[RELATED_TO {similarity}]- Skill (aktarılabilirlik, simetrik)

Kişi düğümü kalıcı değildir; istek sırasında Person -[HAS {level}]-> Skill
olarak puanlamaya girer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

ESSENTIAL_WEIGHT = 1.0
OPTIONAL_WEIGHT = 0.4


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    category: str
    learn_weeks: float
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class Requirement:
    skill_id: str
    weight: float
    essential: bool


@dataclass(frozen=True)
class Market:
    postings_90d: int
    trend: float
    candidates: int


@dataclass(frozen=True)
class Role:
    id: str
    title: str
    kind: str
    esco_code: str | None
    product: str | None
    requirements: tuple[Requirement, ...]
    market: Market


@dataclass
class SkillGraph:
    skills: dict[str, Skill] = field(default_factory=dict)
    roles: dict[str, Role] = field(default_factory=dict)
    # skill_id -> {komşu skill_id: benzerlik}
    related: dict[str, dict[str, float]] = field(default_factory=dict)

    def add_skill(self, skill: Skill) -> None:
        self.skills[skill.id] = skill
        self.related.setdefault(skill.id, {})

    def relate(self, a: str, b: str, similarity: float) -> None:
        if not 0 < similarity <= 1:
            raise ValueError(f"Benzerlik 0-1 aralığında olmalı: {a}-{b}={similarity}")
        # Simetrik kenar; iki yönde farklı değer verildiyse yükseği geçerli.
        for x, y in ((a, b), (b, a)):
            current = self.related.setdefault(x, {}).get(y, 0.0)
            self.related[x][y] = max(current, similarity)

    def add_role(self, role: Role) -> None:
        for req in role.requirements:
            if req.skill_id not in self.skills:
                raise ValueError(f"{role.id} bilinmeyen beceri istiyor: {req.skill_id}")
        self.roles[role.id] = role

    def neighbors(self, skill_id: str) -> dict[str, float]:
        return self.related.get(skill_id, {})


def load_graph(data_dir: Path = DATA_DIR) -> SkillGraph:
    skills_doc = json.loads((data_dir / "skills.json").read_text(encoding="utf-8"))
    roles_doc = json.loads((data_dir / "roles.json").read_text(encoding="utf-8"))

    graph = SkillGraph()
    for s in skills_doc["skills"]:
        graph.add_skill(
            Skill(
                id=s["id"],
                name=s["name"],
                category=s["category"],
                learn_weeks=float(s["learn_weeks"]),
                aliases=tuple(s.get("aliases", [])),
            )
        )
    for s in skills_doc["skills"]:
        for other, sim in s.get("related", {}).items():
            if other not in graph.skills:
                raise ValueError(f"{s['id']} bilinmeyen beceriyle ilişkili: {other}")
            graph.relate(s["id"], other, float(sim))

    for r in roles_doc["roles"]:
        reqs = [Requirement(sid, ESSENTIAL_WEIGHT, True) for sid in r["essential"]]
        reqs += [
            Requirement(sid, OPTIONAL_WEIGHT, False)
            for sid in r.get("optional", [])
            if sid not in r["essential"]
        ]
        m = r["market"]
        graph.add_role(
            Role(
                id=r["id"],
                title=r["title"],
                kind=r.get("kind", "genel"),
                esco_code=r.get("esco_code"),
                product=r.get("product"),
                requirements=tuple(reqs),
                market=Market(int(m["postings_90d"]), float(m["trend"]), int(m["candidates"])),
            )
        )
    return graph
