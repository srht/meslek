(() => {
  "use strict";

  const LEVELS = [[1, "Temel"], [2, "Orta"], [3, "İleri"]];
  const SAMPLE_CV =
    "6 yıl Java ve Spring Boot ile backend geliştirme yaptım. PostgreSQL ve PL/SQL ile " +
    "veri katmanı, REST API tasarımı, Kafka ile sistemler arası entegrasyon. Docker ve " +
    "Jenkins pipeline kullanıyorum, Git ile çalışıyorum. Son projemde muhasebe ve satın alma " +
    "süreçlerini dijitalleştiren bir ekipteydim. Temel düzeyde React bilgim var.";

  const $ = (sel) => document.querySelector(sel);
  const state = { catalog: [], byId: new Map(), person: new Map() };

  async function api(path, body) {
    const res = await fetch(path, body === undefined ? {} : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`${path}: ${res.status}`);
    return res.json();
  }

  function el(tag, attrs = {}, text) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // ---- Beceri listesi ------------------------------------------------------

  function renderSkills() {
    const list = $("#skills");
    list.replaceChildren();
    const entries = [...state.person.entries()].sort((a, b) =>
      state.byId.get(a[0]).name.localeCompare(state.byId.get(b[0]).name, "tr"));
    for (const [id, level] of entries) {
      const li = el("li");
      li.append(el("span", { class: "name", title: state.byId.get(id).name }, state.byId.get(id).name));
      const select = el("select", { "aria-label": `${state.byId.get(id).name} seviyesi` });
      for (const [value, label] of LEVELS) {
        const opt = el("option", { value }, label);
        if (value === level) opt.selected = true;
        select.append(opt);
      }
      select.addEventListener("change", () => state.person.set(id, Number(select.value)));
      const remove = el("button", { class: "remove", type: "button", "aria-label": "Kaldır" }, "×");
      remove.addEventListener("click", () => { state.person.delete(id); renderSkills(); });
      li.append(select, remove);
      list.append(li);
    }
    $("#skills-empty").hidden = state.person.size > 0;
    $("#recommend").disabled = state.person.size === 0;
  }

  function addSkillByName() {
    const input = $("#skill-search");
    const q = input.value.trim().toLocaleLowerCase("tr");
    if (!q) return;
    const hit = state.catalog.find((s) => s.name.toLocaleLowerCase("tr") === q)
      || state.catalog.find((s) => s.name.toLocaleLowerCase("tr").includes(q));
    if (!hit) { input.setCustomValidity("Bu beceri katalogda yok"); input.reportValidity(); return; }
    input.setCustomValidity("");
    if (!state.person.has(hit.id)) state.person.set(hit.id, 2);
    input.value = "";
    renderSkills();
  }

  async function extract() {
    const text = $("#cv").value.trim();
    if (!text) return;
    const btn = $("#extract");
    btn.disabled = true;
    btn.textContent = "Çıkarılıyor…";
    try {
      const { skills: found, method, note } = await api("/api/extract", { text });
      for (const s of found) state.person.set(s.skill_id, s.level);
      renderSkills();
      const info = $("#extract-info");
      info.textContent = note
        || (method === "gemini"
          ? `${found.length} beceri yapay zekâ (Gemini) ile çıkarıldı.`
          : `${found.length} beceri anahtar kelime eşleştirmesiyle çıkarıldı.`);
      info.hidden = false;
      if (!found.length) alert("Metinde tanıdığımız bir beceri bulamadık; elle ekleyebilirsin.");
    } catch (e) {
      alert("Beceriler çıkarılamadı: " + e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "Becerileri çıkar";
    }
  }

  // ---- Öneriler ------------------------------------------------------------

  const pct = (x) => Math.round(x * 100);

  function metric(label, value, ratio) {
    const wrap = el("div");
    wrap.append(el("dt", {}, label), el("dd", {}, value));
    const meter = el("div", { class: "meter", role: "presentation" });
    const fill = el("i");
    fill.style.width = `${pct(ratio)}%`;
    meter.append(fill);
    wrap.append(meter);
    return wrap;
  }

  function renderResult(rec) {
    const node = $("#result-tpl").content.firstElementChild.cloneNode(true);
    node.querySelector(".r-title").textContent = rec.title;
    const tags = node.querySelector(".r-tags");
    if (rec.product) tags.append(el("span", { class: "tag product" }, `${rec.product} uzmanlığı`));
    if (rec.ready) tags.append(el("span", { class: "tag" }, "Temel beceriler tamam"));
    if (rec.gap_weeks > 0) tags.append(el("span", { class: "tag" }, `~${Math.round(rec.gap_weeks)} hafta öğrenme`));
    node.querySelector(".r-score span").textContent = pct(rec.score);

    node.querySelector(".metrics").append(
      metric("Örtüşme", `%${pct(rec.overlap)}`, rec.overlap),
      metric("Hazırlık", rec.gap_weeks ? `${Math.round(rec.gap_weeks)} hf` : "Hazır", rec.readiness),
      metric("Talep", `${rec.postings_90d} ilan`, rec.demand),
      metric("Fırsat", `${rec.candidates_per_posting} aday/ilan`, rec.opportunity),
    );

    const reasons = node.querySelector(".reasons");
    for (const r of rec.reasons) reasons.append(el("li", {}, r));

    const chips = node.querySelector(".chips");
    for (const m of rec.matched) chips.append(el("span", { class: "chip have", title: "Sahipsin" }, `✓ ${m.name}`));
    for (const m of rec.transferred) {
      const via = state.byId.get(m.via)?.name ?? m.via;
      chips.append(el("span", { class: "chip transfer", title: `${via} becerinden aktarım` }, `↗ ${m.name}`));
    }
    for (const m of rec.missing) {
      if (rec.transferred.some((t) => t.skill_id === m.skill_id)) continue;
      const cls = "chip gap" + (m.essential ? "" : " optional");
      const label = `+ ${m.name} · ${Math.round(m.weeks_to_learn)} hf` + (m.essential ? "" : " (artı değer)");
      chips.append(el("span", { class: cls }, label));
    }
    return node;
  }

  async function showRecommendations() {
    const btn = $("#recommend");
    btn.disabled = true;
    try {
      const body = {
        skills: [...state.person].map(([skill_id, level]) => ({ skill_id, level })),
        include_ready: !$("#hide-ready").checked,
        limit: 5,
      };
      const { recommendations } = await api("/api/recommend", body);
      const box = $("#results");
      box.replaceChildren(...recommendations.map(renderResult));
      if (!recommendations.length) box.append(el("p", { class: "empty" }, "Uygun pozisyon bulunamadı."));
      $("#results-section").hidden = false;
      $("#results-section").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
      alert("Öneriler alınamadı: " + e.message);
    } finally {
      btn.disabled = state.person.size === 0;
    }
  }

  // ---- Başlangıç -----------------------------------------------------------

  async function init() {
    state.catalog = await api("/api/skills");
    for (const s of state.catalog) state.byId.set(s.id, s);
    $("#skill-options").replaceChildren(...state.catalog.map((s) => el("option", { value: s.name })));

    $("#extract").addEventListener("click", extract);
    $("#sample").addEventListener("click", () => { $("#cv").value = SAMPLE_CV; });
    $("#add-skill").addEventListener("click", addSkillByName);
    $("#skill-search").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addSkillByName(); } });
    $("#skill-search").addEventListener("input", (e) => e.target.setCustomValidity(""));
    $("#recommend").addEventListener("click", showRecommendations);
    renderSkills();
  }

  init().catch((e) => alert("Uygulama yüklenemedi: " + e.message));
})();
