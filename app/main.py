from __future__ import annotations

import logging
import os
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .extract import SkillExtractor
from .graph import load_graph
from .llm_extract import DEFAULT_MODEL, GeminiError, GeminiExtractor
from .scoring import recommend

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

graph = load_graph()
extractor = SkillExtractor(graph)
log = logging.getLogger("meslek")

# GEMINI_API_KEY varsa CV çıkarımı Gemini ile yapılır; hata olursa sözlük yedeği devreye girer.
gemini = (
    GeminiExtractor(graph, os.environ["GEMINI_API_KEY"], model=os.environ.get("GEMINI_MODEL", DEFAULT_MODEL))
    if os.environ.get("GEMINI_API_KEY")
    else None
)

app = FastAPI(title="Meslek Köprüsü", version="0.1.0")


class PersonSkill(BaseModel):
    skill_id: str
    level: int = Field(2, ge=1, le=3)


class RecommendRequest(BaseModel):
    skills: list[PersonSkill]
    limit: int = Field(5, ge=1, le=20)
    include_ready: bool = True


class ExtractRequest(BaseModel):
    text: str = Field(..., max_length=50_000)


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {
        "status": "ok",
        "skills": len(graph.skills),
        "roles": len(graph.roles),
        "extractor": f"gemini:{gemini.model}" if gemini else "sozluk",
    }


@app.get("/api/skills")
def list_skills():
    return [
        {"id": s.id, "name": s.name, "category": s.category, "learn_weeks": s.learn_weeks}
        for s in sorted(graph.skills.values(), key=lambda s: (s.category, s.name.lower()))
    ]


@app.get("/api/roles")
def list_roles():
    return [
        {
            "id": r.id,
            "title": r.title,
            "kind": r.kind,
            "product": r.product,
            "esco_code": r.esco_code,
            "essential": [q.skill_id for q in r.requirements if q.essential],
            "optional": [q.skill_id for q in r.requirements if not q.essential],
            "market": asdict(r.market),
        }
        for r in graph.roles.values()
    ]


@app.get("/api/graph")
def graph_export():
    """Görselleştirme için düğüm/kenar listesi."""
    nodes = [{"id": s.id, "label": s.name, "type": "skill", "category": s.category} for s in graph.skills.values()]
    nodes += [{"id": r.id, "label": r.title, "type": "role", "kind": r.kind} for r in graph.roles.values()]
    edges = [
        {"source": r.id, "target": q.skill_id, "type": "REQUIRES", "weight": q.weight}
        for r in graph.roles.values()
        for q in r.requirements
    ]
    edges += [
        {"source": a, "target": b, "type": "RELATED_TO", "weight": sim}
        for a, nbrs in graph.related.items()
        for b, sim in nbrs.items()
        if a < b
    ]
    return {"nodes": nodes, "edges": edges}


@app.post("/api/extract")
def extract_skills(req: ExtractRequest):
    method, note = "sozluk", None
    if gemini is not None:
        try:
            skills = gemini.extract(req.text)
            method = "gemini"
        except GeminiError as e:
            log.warning("Gemini çıkarımı başarısız, sözlüğe dönülüyor: %s", e)
            note = "Yapay zekâ çıkarımı şu an kullanılamıyor; anahtar kelime eşleştirmesi kullanıldı."
    if method == "sozluk":
        skills = extractor.extract(req.text)
    return {"skills": [asdict(s) for s in skills], "method": method, "note": note}


@app.post("/api/recommend")
def recommend_roles(req: RecommendRequest):
    person = {s.skill_id: s.level for s in req.skills}
    unknown = sorted(k for k in person if k not in graph.skills)
    recs = recommend(graph, person, limit=req.limit, include_ready=req.include_ready)
    return {"recommendations": [r.to_dict() for r in recs], "unknown_skills": unknown}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")
