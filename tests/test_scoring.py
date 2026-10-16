from app.extract import SkillExtractor
from app.graph import load_graph
from app.scoring import recommend

graph = load_graph()


def test_graph_loads_and_is_consistent():
    assert len(graph.skills) > 30
    assert len(graph.roles) > 10
    for a, nbrs in graph.related.items():
        for b, sim in nbrs.items():
            assert graph.related[b][a] == sim  # simetrik


def test_java_developer_gets_product_paths():
    person = {"java": 3, "sql": 3, "rest_api": 3, "git": 3, "integration_patterns": 2, "erp_concepts": 2}
    recs = recommend(graph, person, limit=13)
    by_id = {r.role_id: r for r in recs}
    # Mevcut profil eksiksiz eşleşmeli
    assert by_id["backend_java"].gap_weeks == 0
    # Java -> Apex aktarımı Salesforce yolunda görünmeli
    sf = by_id["salesforce_dev"]
    assert any(t.skill_id == "apex" and t.via == "java" for t in sf.transferred)
    # Niş ürün rolleri genel rollerden daha yüksek fırsat skoru almalı
    assert by_id["sap_cpi"].opportunity > by_id["backend_java"].opportunity


def test_hide_ready_excludes_complete_matches():
    person = {"java": 2, "sql": 2, "rest_api": 2, "git": 2}
    recs = recommend(graph, person, limit=20, include_ready=False)
    assert all(not r.ready for r in recs)
    assert "backend_java" not in {r.role_id for r in recs}


def test_unknown_skills_ignored_and_empty_returns_nothing():
    assert recommend(graph, {"cobol_from_mars": 3}) == []


def test_level_affects_score():
    low = recommend(graph, {"java": 1, "sql": 1}, limit=20)
    high = recommend(graph, {"java": 3, "sql": 3}, limit=20)
    score = lambda recs, rid: next(r.score for r in recs if r.role_id == rid)
    assert score(high, "backend_java") > score(low, "backend_java")


def test_extractor_longest_match_and_levels():
    ex = SkillExtractor(graph)
    found = {s.skill_id: s for s in ex.extract(
        "7 yıl Java, Spring Boot. SAP CPI ile entegrasyon. C# ve .NET, temel düzeyde React. CI/CD ve API tasarımı."
    )}
    assert "sap_cpi" in found
    assert "sap_modules" not in found  # "SAP CPI" genel SAP olarak sayılmamalı
    assert "csharp" in found
    assert "ci_cd" in found
    assert found["java"].level == 3
    assert found["react"].level == 1
