# AI Premium Laptop Fırsat Avcısı

Almanya'daki **premium Windows laptop** fırsatlarını otomatik takip eden, donanım ve kalite
kriterlerine göre analiz eden ve yalnızca gerçekten alınmaya değer modelleri **Telegram** üzerinden
bildiren kişisel bir satın alma asistanı.

Amaç sadece "ucuz laptop" bulmak değil; MacBook kalitesine yaklaşan, güçlü GPU'lu, mühendislik
yazılımlarını (SolidWorks, AutoCAD, ANSYS) kaldırabilen, uzun ömürlü premium cihazları yakalamaktır.

> Bu depo, projenin **Aşama 1 (MVP)** uygulamasını içerir: MyDealz kişisel alarm RSS kaynağı,
> ucuz kural tabanlı ön filtre, Gemini AI karar motoru, deterministik fırsat skoru, SQLite mükerrer
> kontrolü ve Telegram bildirimi.

---

## Nasıl Çalışır?

```
MyDealz RSS  ──▶  Dedup (SQLite)  ──▶  Ön Filtre  ──▶  Gemini AI Analizi  ──▶  Skor (0-100)
                                       (ucuz kural)     (zorunlu JSON)         (deterministik)
                                                                                     │
                                          approved && skor >= 75  ◀──────────────────┘
                                                   │
                                                   ▼
                                           Telegram Bildirimi
```

Her ilan AI'a gitmeden önce ucuz kurallarla elenir (laptop mı, reddedilen seri mi, GPU eşiği,
fiyat aralığı, daha önce görüldü mü). Böylece API maliyeti düşer. Geçen ilanlar Gemini ile analiz
edilir; AI **her zaman JSON** döndürür. Nihai skor `analyzers/scoring.py` içinde deterministik
hesaplanır (AI alanları girdi olur). Sadece `approved && deal_score >= min_deal_score` olan ilanlar
Telegram'a düşer.

## Proje Yapısı

```
sources/        base.py (DealSource arayüzü) · mydealz.py (RSS okuyucu)
analyzers/      pre_filter.py · base_analyzer.py · gemini_analyzer.py (+DryRun) · scoring.py · spec_validator.py
notifications/  telegram_notifier.py
storage/        models.py · database.py (SQLite)
main.py         scheduler + orkestrasyon
config.yaml     filtreler, eşikler, kaynaklar
tests/          birim testleri + offline örnek feed/config
```

Mimari çoklu kaynak için genişletilebilir: yeni bir kaynak `DealSource` arayüzünü, yeni bir AI
sağlayıcı `LLMAnalyzer` arayüzünü uygular (ileride idealo/geizhals, Claude vb.).

---

## Kurulum

```powershell
# 1) Sanal ortam
python -m venv .venv
.venv\Scripts\activate

# 2) Bağımlılıklar
pip install -r requirements.txt

# 3) Sırları ayarla
copy .env.example .env        # GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID doldur

# 4) Yapılandırma
copy config.example.yaml config.yaml
```

`config.yaml` içinde **`sources.mydealz.feeds`** alanına MyDealz hesabınızdan oluşturduğunuz
kişisel deal-alarm RSS URL'lerinizi ekleyin. Filtreleri (`min_gpu`, `min_ram_gb`, `min_deal_score`,
`reject_keywords`, `preferred_models`) zevkinize göre düzenleyin.

## Çalıştırma

```powershell
# Anahtarsız uçtan uca test (Gemini ve Telegram mock; mesaj konsola basılır)
python main.py --once --dry-run --config tests/sample_config.yaml

# Tek tarama (gerçek mod — .env'de anahtarlar gerekli)
python main.py --once

# Sürekli mod (config'deki polling.interval_seconds ile)
python main.py
```

`GEMINI_API_KEY` tanımlı değilse sistem otomatik olarak **DryRunAnalyzer**'a düşer (kaba kural
tabanlı analiz), böylece anahtarsız da çalışır.

### Testler

```powershell
python tests/test_prefilter_scoring.py    # ya da: python -m pytest -q
```

---

## Fırsat Skoru (0-100)

| Bileşen | Puan |
|---|---|
| Gerçek indirim oranı | 25 |
| GPU gücü ve TGP | 20 |
| RAM miktarı + yükseltilebilirlik | 15 |
| Kasa kalitesi | 15 |
| Ekran kalitesi | 10 |
| Mühendislik yazılımı uygunluğu | 10 |
| Marka/model güvenilirliği | 5 |

**Karar eşikleri:** 90+ kaçırılmaz · 80-89 çok güçlü · 70-79 alınabilir · 60-69 sınırda · <60 bildirilmez.
Telegram bildirimi yalnızca `deal_score >= min_deal_score (varsayılan 70)` ve `approved` ise gönderilir.

## Hedef Kriterler (özet)

- **Zorunlu:** min RTX 4060 · min 32 GB RAM (veya kesin yükseltilebilir 16 GB) · premium metal kasa · gerçek indirim
- **Otomatik ret:** Asus TUF · HP Victus · Acer Nitro · MSI Thin/GF/Cyborg · RTX 4050 ve altı · 8 GB RAM · zayıf ekran/kasa
- **Premium aileler (pozitif puan):** ROG Zephyrus/Flow · Legion 7/Slim 7/Pro · Yoga Pro · XPS 15/16 · Precision · ZBook · Razer Blade · MSI Stealth/Creator · Schenker/XMG

---

## Güvenlik

- API anahtarları asla koda yazılmaz; `.env` içinde tutulur (`.gitignore`'da).
- Kaynak sitelere aşırı istek atılmaz; tarayıcı benzeri User-Agent ile RSS okunur.
- Satın alma otomatik yapılmaz — sistem yalnızca bildirir; son kararı kullanıcı verir.

## Yol Haritası

- **Aşama 2:** Gemini JSON şema zorunluluğunu sıkılaştırma, TGP doğrulama, kasa/RAM sınıflandırması.
- **Aşama 3:** Idealo · Geizhals · Notebooksbilliger · Lenovo Campus · Dell Outlet kaynakları.
- **Aşama 4:** Telegram geri bildirim butonları, whitelist/blacklist, bütçe modu.
- **Aşama 5:** Web dashboard (geçmiş, skor dağılımı, kaynak analizi).
