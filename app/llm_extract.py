"""Gemini API ile CV'den beceri çıkarımı.

Sözlük tabanlı çıkarıcının (extract.py) yapamadıklarını hedefler:
olumsuzluk ("Java bilmiyorum"), dolaylı anlatım ("sipariş sistemleri geliştirdim"
-> ERP kavramları) ve yılı doğru beceriye bağlama.

Model yalnızca katalogdaki beceri kimliklerini döndürebilir; yanıt şeması
skill_id alanını enum ile sınırlar ve dönen veri burada tekrar doğrulanır.
"""

from __future__ import annotations

import json
import logging

import httpx

from .extract import ExtractedSkill
from .graph import SkillGraph

log = logging.getLogger(__name__)

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-3.8-flash"

SYSTEM_PROMPT = """Sen bir kariyer danışmanlığı sistemi için CV analiz ediyorsun.
Görevin: metindeki kişinin GERÇEKTEN sahip olduğu becerileri, verilen katalogdan seçmek.

Kurallar:
- Yalnızca katalogdaki skill_id değerlerini kullan. Katalogda karşılığı olmayan beceriyi atla.
- Olumsuz veya istek bildiren ifadeleri beceri sayma ("bilmiyorum", "öğrenmek istiyorum", "ilgileniyorum").
- Dolaylı anlatılan becerileri çıkar: ör. "Spring Boot ile servis yazdım" -> java;
  "sipariş ve stok süreçleri" -> erp_concepts; "mikroservisler arası mesajlaşma" -> integration_patterns.
- Seviye: 1 = temel (yeni başlamış, kurs, <1 yıl, "temel düzey"),
  2 = orta (iş ortamında kullanmış, 1-3 yıl),
  3 = ileri (4+ yıl, uzman/kıdemli/lider, karmaşık işlerde derinlemesine).
  Belirti yoksa 2 ver.
- years: metinde o beceriye açıkça bağlanan yıl varsa yaz, yoksa 0.
- evidence: metinden o beceriyi destekleyen kısa, birebir alıntı (en fazla 120 karakter).
"""


class GeminiError(RuntimeError):
    pass


class GeminiExtractor:
    def __init__(
        self,
        graph: SkillGraph,
        api_key: str,
        model: str = DEFAULT_MODEL,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ):
        self.graph = graph
        self.api_key = api_key
        self.model = model
        self.client = client or httpx.Client(timeout=timeout)
        self._catalog = "\n".join(
            f"- {s.id}: {s.name} (örn. {', '.join(s.aliases[:5])})" for s in graph.skills.values()
        )

    def _schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "skills": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "skill_id": {"type": "STRING", "enum": sorted(self.graph.skills)},
                            "level": {"type": "INTEGER"},
                            "years": {"type": "NUMBER"},
                            "evidence": {"type": "STRING"},
                        },
                        "required": ["skill_id", "level", "evidence"],
                    },
                }
            },
            "required": ["skills"],
        }

    def extract(self, text: str) -> list[ExtractedSkill]:
        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"Beceri kataloğu:\n{self._catalog}\n\nCV metni:\n<cv>\n{text}\n</cv>"}],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": self._schema(),
            },
        }
        try:
            res = self.client.post(
                API_URL.format(model=self.model),
                headers={"x-goog-api-key": self.api_key},
                json=body,
            )
        except httpx.HTTPError as e:
            raise GeminiError(f"Gemini isteği başarısız: {e}") from e
        if res.status_code != 200:
            raise GeminiError(f"Gemini {res.status_code}: {res.text[:300]}")
        return self._parse(res.json())

    def _parse(self, payload: dict) -> list[ExtractedSkill]:
        try:
            parts = payload["candidates"][0]["content"]["parts"]
            raw = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            items = json.loads(raw)["skills"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
            raise GeminiError(f"Gemini yanıtı çözümlenemedi: {e}") from e

        found: dict[str, ExtractedSkill] = {}
        for item in items:
            sid = item.get("skill_id")
            if sid not in self.graph.skills:
                continue
            try:
                level = max(1, min(3, int(item.get("level", 2))))
                years = float(item.get("years") or 0) or None
            except (TypeError, ValueError):
                level, years = 2, None
            prev = found.get(sid)
            if prev is None or level > prev.level:
                found[sid] = ExtractedSkill(
                    skill_id=sid,
                    name=self.graph.skills[sid].name,
                    level=level,
                    evidence=str(item.get("evidence", ""))[:200],
                    years=years,
                    source="gemini",
                )
        return sorted(found.values(), key=lambda s: s.name.lower())
