# Meslek Köprüsü

Belirli bir unvanla iş bulamayan bir meslek erbabını, becerilerinin büyük kısmını
kullanabileceği **komşu pozisyonlara** (özellikle niş ürün uzmanlıklarına)
yönlendiren graf tabanlı öneri sistemi.

> “Developer” kalabalık, ama “SAP entegrasyonu bilen developer” az.

Sistemin cevapladığı soru: *Mevcut becerilerinle, en az ek öğrenmeyle, en çok talep
gören hangi pozisyona geçebilirsin ve neyi öğrenmen gerekiyor?*

## Çalıştırma

```bash
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
# http://127.0.0.1:8000
pytest
```

## Docker / Dokploy

```bash
docker build -t meslek .
docker run -p 8000:8000 meslek
```

Dokploy'da:

1. **Create Application** → Provider: GitHub, repo `srht/meslek`, istediğin dal.
2. **Build Type: Dockerfile** (Docker File: `Dockerfile`, Build Path: `/`).
3. **Domains** → alan adını ekle, **Container Port: `8000`**, HTTPS açık (Let's Encrypt).
4. **Deploy**. Sağlık kontrolü `GET /healthz` adresinde; Dockerfile'daki `HEALTHCHECK` bunu kullanır.

### Gemini ile CV çıkarımı

Dokploy'da **Environment** sekmesine ekle:

```
GEMINI_API_KEY=...            # https://aistudio.google.com/apikey
GEMINI_MODEL=gemini-3.8-flash # isteğe bağlı, varsayılan bu
```

Anahtar yoksa ya da Gemini hata verirse (kota, ağ, geçersiz yanıt) sistem otomatik olarak
anahtar kelime sözlüğüne döner. Hangi yöntemin etkin olduğu `GET /healthz` yanıtındaki
`extractor` alanında görünür. CV metni Google'a gönderildiği için KVKK açısından aydınlatma
metninde belirtilmeli.

Portu değiştirmek istersen `PORT` ortam değişkenini ayarla ve domain'deki Container Port'u da aynı değere getir.
Alternatif olarak Build Type `Docker Compose` seçilip `docker-compose.yml` kullanılabilir.

## Graf şeması

| Düğüm | Açıklama |
|---|---|
| `Skill` | Beceri. Ürün uzmanlıkları (ABAP, Apex, X++…) da `category: "ürün"` olan becerilerdir. |
| `Role` | Pozisyon; ESCO/ISCO meslek grubu kodu ve pazar verisi (ilan, eğilim, aday havuzu) taşır. |
| `Person` | Kalıcı değil; istek anında `HAS {level}` kenarlarıyla puanlamaya girer. |

| Kenar | Açıklama |
|---|---|
| `Role -[REQUIRES {weight}]-> Skill` | Temel (1.0) veya isteğe bağlı (0.4) gereksinim |
| `Skill -[RELATED_TO {similarity}]- Skill` | Aktarılabilirlik (ör. Java ↔ Apex 0.7) |

Veri: `data/skills.json`, `data/roles.json`.

## Puanlama (`app/scoring.py`)

| Alt skor | Ağırlık | Hesap |
|---|---|---|
| Örtüşme | %40 | Ağırlıklı gereksinim karşılama. Seviye kredisi: temel 0.5, orta 0.8, ileri 1.0. Sahip olunmayan beceriye komşu beceriden `benzerlik × seviye × 0.6` aktarım kredisi. |
| Hazırlık | %25 | Eksik temel becerilerin tahmini öğrenme haftası; 40 hafta = 0. |
| Talep | %20 | log(90 günlük ilan) normalize × (1 + yıllık eğilim) |
| Fırsat | %15 | log(ilan / aday) normalize; niş ürün rolleri öne çıkar |

Her öneri gerekçe cümleleriyle döner (“Bu pozisyon için son 90 günde 140 ilan var,
örtüşme %49, eksik: SAP CPI, SOAP — ~12 hafta”).

## API

- `GET /api/skills`: beceri kataloğu
- `GET /api/roles`: pozisyonlar ve gereksinimleri
- `GET /api/graph`: görselleştirme için düğüm/kenar listesi
- `POST /api/extract` `{text}`: CV metninden beceri ve tahmini seviye; yanıt `{skills, method: "gemini"|"sozluk", note}`
- `POST /api/recommend` `{skills:[{skill_id, level}], limit, include_ready}`

## Durum ve yol haritası

**Önemli:** `roles.json` içindeki pazar rakamları **temsili örnek veridir**; arayüz de bunu belirtiyor.

1. **ESCO içe aktarma:** Yazılım meslekleri ve becerilerini ESCO API/CSV'den çekip `esco_uri` ile eşlemek.
2. **Talep katmanı:** İlanlardan LLM ile beceri ve ürün uzmanlığı çıkarmak. Kaynak olarak kurumsal ortaklık ya da kullanıcıların yüklediği ilanlar (site kullanım koşulları ve KVKK).
3. **CV çıkarımı:** ~~LLM tabanlı çıkarım~~ Gemini ile eklendi (`app/llm_extract.py`); sırada PDF/DOCX yükleme var.
4. **Geçiş sonucu verisi:** Kullanıcıların gerçek geçiş sonuçlarını toplayıp `RELATED_TO` ağırlıklarını ve skorları kalibre etmek.
5. **Kalıcı graf deposu:** Veri büyüyünce Neo4j ya da PostgreSQL + pgvector'e taşımak.
