"""CV / serbest metinden beceri çıkarımı.

Şimdilik takma ad (alias) sözlüğüyle eşleştirme yapılır: en uzun eşleşme önce
alınır ve metnin o kısmı tüketilir, böylece "SAP CPI" hem CPI hem genel SAP
olarak iki kez sayılmaz. İleride burası LLM tabanlı çıkarımla değiştirilecek;
arayüz aynı kalır.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .graph import SkillGraph

# Kıdem ipuçları: eşleşmenin yakınında geçerse seviye tahmini yükselir.
_SENIOR_HINTS = ("ileri", "uzman", "expert", "senior", "kıdemli", "advanced", "lead")
_JUNIOR_HINTS = ("temel", "başlangıç", "basic", "beginner", "junior", "giriş")
_YEARS = re.compile(r"(\d{1,2})\+?\s*(?:yıl|yil|year|years|yr)")


def turkish_lower(text: str) -> str:
    # "I" -> "ı" dönüşümü bilinçli olarak yapılmıyor: CV'lerdeki teknik terimler
    # (API, CI/CD) çoğunlukla İngilizce. Sadece "İ"nin birleşik nokta üretmesini önlüyoruz.
    return text.replace("İ", "i").lower()


@dataclass
class ExtractedSkill:
    skill_id: str
    name: str
    level: int
    evidence: str


def _alias_pattern(alias: str) -> re.Pattern[str]:
    # \b, "c#" veya ".net" gibi kelime dışı karakterle biten/başlayan takma
    # adlarda çalışmadığı için sınırları elle tanımlıyoruz.
    return re.compile(r"(?<![\w.+#])" + re.escape(alias) + r"(?![\w+#])")


class SkillExtractor:
    def __init__(self, graph: SkillGraph):
        self.graph = graph
        entries = []
        for skill in graph.skills.values():
            names = {turkish_lower(a) for a in skill.aliases} | {turkish_lower(skill.name)}
            for alias in names:
                entries.append((alias, skill.id))
        entries.sort(key=lambda e: len(e[0]), reverse=True)
        self._patterns = [(_alias_pattern(a), sid) for a, sid in entries]

    def extract(self, text: str) -> list[ExtractedSkill]:
        lowered = turkish_lower(text)
        consumed = [False] * len(lowered)
        found: dict[str, ExtractedSkill] = {}

        for pattern, skill_id in self._patterns:
            for m in pattern.finditer(lowered):
                start, end = m.span()
                if any(consumed[start:end]):
                    continue
                for i in range(start, end):
                    consumed[i] = True
                level = self._guess_level(lowered, start, end)
                prev = found.get(skill_id)
                if prev is None or level > prev.level:
                    found[skill_id] = ExtractedSkill(
                        skill_id=skill_id,
                        name=self.graph.skills[skill_id].name,
                        level=level,
                        evidence=text[start:end],
                    )
        return sorted(found.values(), key=lambda s: s.name.lower())

    @staticmethod
    def _guess_level(text: str, start: int, end: int) -> int:
        window = text[max(0, start - 40) : min(len(text), end + 40)]
        years = [int(y) for y in _YEARS.findall(window)]
        if any(h in window for h in _SENIOR_HINTS) or (years and max(years) >= 4):
            return 3
        if any(h in window for h in _JUNIOR_HINTS) or (years and max(years) <= 1):
            return 1
        return 2
