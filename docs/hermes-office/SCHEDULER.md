# Hermes Office — Scheduler

Nov 16, 2026 · @Shin · Mengikat `webhook_server/scheduler.py`. Endpoint: [API-REFERENCE.md](API-REFERENCE.md).

Semua job berkala hidup di proses sidecar (FastAPI + APScheduler `BackgroundScheduler`), zona waktu
**Asia/Jakarta (WIB)**. Tidak ada job yang dijalankan dari UI, dan tidak ada job yang memanggil
Express secara langsung — kantor hanya menerima event lewat bridge.

---

## 1. Prinsip

1. **Semua trigger bisnis lewat Orchestrator** (fix Rev 3 #5). Pengecualian hanya job internal yang
   tidak menghasilkan karakter: cleanup, sweep, backup.
2. **API scheduler dipasang di startup, bukan saat import** (Rev 3.1 #6). `uvicorn --reload`
   meng-import modul dua kali; scheduler yang start saat import akan punya job dobel.
3. **`max_instances=1`, `coalesce=True`, `misfire_grace_time` eksplisit.** Laptop tidur 2 jam tidak
   boleh menghasilkan 24 kali cek email berturut-turut.
4. **Job tidak boleh melempar.** Setiap job membungkus badan dengan `try/except`, log, dan
   melanjutkan; scheduler tidak pernah mati karena satu kegagalan.
5. **Id job stabil** — dipakai untuk pause/resume/observasi.

---

## 2. Daftar job

| id | Jadwal | Fungsi | Lewat Orchestrator? | Timeout internal |
| --- | --- | --- | --- | --- |
| `email_check` | tiap 5 menit | `check_new_emails` → trigger `new_email` | **ya** | 60 dtk |
| `sla_check` | tiap 5 menit | `check_sla_breaches` (Support langsung) | tidak | 300 dtk (approval) |
| `ops_check` | tiap jam | `run_ops_check` (Ops langsung) | tidak | 120 dtk |
| `episode_embargo` | tiap 1 menit | `run_episode_scheduler` (EpisodeScheduler) | tidak | 30 dtk |
| `weekly_report` | Senin 09.00 | `run_marketing_report` → `weekly_analytics` | **ya** | 300 dtk |
| `cache_warmer` | tiap hari 17.00 | `run_cache_warmer` (CacheWarmer) | tidak | 600 dtk |
| `recommendation_batch` | Minggu 22.00 | `run_recommendation_batch` | tidak | 1800 dtk |
| `shared_context_cleanup` | tiap hari 03.00 | `cleanup_shared_context` (24 jam) | tidak | 60 dtk |
| `approval_sweep` | tiap jam | `sweep_approvals` (TTL 24 jam) | tidak | 30 dtk |
| `handoff_check` | tiap 15 menit | `check_handoffs` — handoff lewat deadline | **ya** (eskalasi) | 60 dtk |
| `campaign_retry` | tiap 15 menit | `retry_welcome_campaigns` — surat selamat datang yang gagal terkirim | tidak | 60 dtk |
| `source_health` | tiap 30 menit | `run_source_health` → `GET /v1/admin/sources/health` (Scraper) | tidak | 120 dtk |
| `scraper_backfill` | tiap jam | `run_scraper_backfill` → `POST /v1/admin/scrape/backfill` (Scraper) | tidak | 300 dtk |
| `resolver_refresh` | tiap 6 jam | `run_resolver_refresh` → `POST /v1/admin/media/resolve` (Resolver) | tidak | 600 dtk |
| `db_backup` | tiap hari 02.00 | `backup_databases` (DB-SCHEMA.md §13) | tidak | 300 dtk |

Catatan per job:

- **`email_check`** membaca kotak masuk lewat **IMAP stdlib** (`imaplib`, `hermes_agents/inbox.py`),
  bukan Gmail API: `BODY.PEEK[]` supaya surat tidak hilang kalau proses mati di tengah jalan, UID
  yang sudah jadi tiket dicatat di SharedContext (`inbox:seen`, maks 500). Pesan dengan header
  `Auto-Submitted` selain `no` dilewati — tanpa itu Support menjawab dirinya sendiri. Kalau
  `IMAP_HOST`/`IMAP_USER` kosong, job hanya log **sekali per jam** (bukan tiap 5 menit).
- **`sla_check`** adalah satu-satunya job yang memunculkan permission card dari scheduler. Urutannya
  wajib: `agent_update` → `agent_waiting` → `wait_for_approval` **sekali** (fix Rev 3 #1).
- **`episode_embargo`** memeriksa `episode_schedule` tiap menit: akurasi go-live ±1 menit. Publish
  memakai `UPDATE ... WHERE status='scheduled'` (atomik) supaya DMCA tidak bisa kalah balapan.
- **`handoff_check`** memeriksa `context` key `handoff:*` yang `deadline < now`, lalu
  `run_orchestrator("escalate", {...})`; `escalate` bukan trigger webhook — hanya internal.
- **`approval_sweep`** membuang keputusan approval yang tidak pernah diambil (TTL 24 jam), supaya
  store di memori tidak tumbuh. Ini bukan pengganti timeout agent: agent tetap timeout sendiri.
- **`campaign_retry`** hanya menyentuh catatan `campaign:*` yang `sent: false`. Ia mengirim ulang
  suratnya, **tidak** menulis handoff, jadi Support tidak pernah menerima tiket onboarding kedua
  untuk pelanggan yang sama. Jeda antar-percobaan 15 → 30 → 60 menit (`WELCOME_RETRY_S`), maksimal
  empat percobaan termasuk yang pertama; sesudahnya catatan tetap `sent: false` dengan error
  terakhir — itu masalah manusia, bukan loop. Tanpa `SMTP_HOST` job ini akan mencoba tiga kali lalu
  berhenti, bukan mengirim ribuan baris ke log.

### Status implementasi (W4 → W6)

Sebelas job W6 di §2 terdaftar sejak W6; `campaign_retry` menyusul di W8 sisa (dua belas). Tiga
yang terakhir menunggu agent growth, dan sekarang kerjanya ada di `webhook_server/jobs.py`:

| id | Fungsi | Catatan |
| --- | --- | --- |
| `episode_embargo` | `run_episode_scheduler` | satu putaran `publish_due_episodes`, bukan `while True` |
| `sla_check` | `sla_check` → `SupportAgent.check_sla_breaches` | tiap 5 menit; **satu** card untuk semua tiket telat, `wait_for_approval` sekali |
| `email_check` | `check_new_emails` → `triggers.run_trigger('new_email')` | tiap 5 menit; satu email = satu tiket lewat jalur Orchestrator yang sama dengan webhook |
| `ops_check` | `run_ops_check` → `OpsAgent.check_system` | tiap jam; finding berlevel di log, alert Discord hanya kalau `DISCORD_WEBHOOK_URL` diisi |
| `shared_context_cleanup` | `cleanup_shared_context` | 24 jam; baris `ts` mundur diuji di selfcheck |
| `approval_sweep` | `sweep_approvals` | TTL 24 jam, angka yang sama dengan `approval.TTL_S` |
| `db_backup` | `backup_databases` | `~/.hermes-office/backups/YYYY-MM-DD/` |
| `handoff_check` | `check_handoffs` | tiap 15 menit; **satu** card untuk semua handoff telat, tiga opsi (eskalasi / perpanjang / abaikan) |
| `weekly_report` | `run_marketing_report` | Senin 09.00; `run_trigger('weekly_analytics')` → Orchestrator → Marketing; menulis `media/published/reports/weekly-<ISO week>.md` |
| `cache_warmer` | `run_cache_warmer` | tiap hari 17.00; episode live terbaru di-`GET` dari `CDN_BASE_URL`; tanpa CDN → `warmed: 0` + alasan |
| `recommendation_batch` | `run_recommendation_batch` | Minggu 22.00; co-view dari `ANALYTICS_FEED`, ditulis ke `RECOMMENDATION_DB` (tabel `recommendations`) atau `media/published/recommendations.jsonl` |
| `campaign_retry` | `retry_welcome_campaigns` → `MarketingAgent.retry_welcome` | tiap 15 menit (W8 sisa); hanya `campaign:*` dengan `sent: false`, tidak menulis handoff — tiket onboarding tetap satu per lead |

W9 tidak menambah job: PaymentAgent bekerja dari `POST /webhook/payment`, DMCA dari `/takedown`, dan
SecOps dari `SECURITY_EVENT_FEED` saat dipanggil — bukan dari putaran scheduler. Memasang loop
detik untuk SecOps justru akan membanjiri kantor (PLAN.md §Risiko). Satu-satunya job tambahan
sesudah W6 adalah `campaign_retry` dari W8 sisa; totalnya dua belas, bukan tigabelas.

W10 juga tidak menambah job. Yang disebut W10 sudah aktif tanpa perubahan: `cache_warmer` 17.00
(W6), `weekly_report` Senin 09.00 lewat Orchestrator (W6), `db_backup` 02.00 (W4), dan retensi
berjalan dari trigger `retention_check` (`hermes_agents/retention.py`), bukan dari putaran berkala.
Yang W10 tambahkan hanya datanya: Support mengirim gauge `tickets_pending`, `tickets_resolved`,
`sla_avg_response_min` dan `sla_breach_count` setiap kali tiket berubah, sehingga panel **biz** dan
`/biz` menampilkan angka yang bergerak — `/biz` membacanya lewat `GET /biz-metrics`, dan kantor yang
mati dijawab sebagai kantor yang mati.

W11d menambah tiga job terakhir di tabel: `source_health` (30 menit), `scraper_backfill` (tiap jam) dan
`resolver_refresh` (6 jam), kerjanya di `webhook_server/jobs.py`. Ketiganya internal (tidak lewat
Orchestrator), idempoten, dan tidak melempar: tanpa `ANIWATCH_API_URL` + `ANIWATCH_ADMIN_TOKEN` hasilnya
`ok: false` + alasan yang jelas, dan karakter Scraper/Resolver melaporkan hal itu — bukan "semua sehat".
Totalnya **lima belas** job.

`PENDING_JOBS` tetap ada dan **kosong** sekarang. Itu memang gunanya: job yang kerjanya belum ada
ditulis di sana beserta alasannya, `start_scheduler()` menulis satu baris per entri saat start, dan
`GET /health` mengembalikannya di `pending_jobs` — jadi yang belum ada terlihat sebagai belum ada,
bukan job kosong yang terlihat hidup. Zona waktu: `HERMES_TZ` (default `Asia/Jakarta`).

---

## 3. Implementasi

```python
# webhook_server/scheduler.py
import logging, time
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

_log = logging.getLogger(__name__)
_sched: BackgroundScheduler | None = None

COMMON = dict(max_instances=1, coalesce=True, misfire_grace_time=300)


def _guard(fn):
    """Satu job gagal tidak boleh mematikan scheduler."""
    def wrapper(*a, **kw):
        try:
            fn(*a, **kw)
        except Exception:
            _log.exception("scheduler job %s gagal", fn.__name__)
    return wrapper


def start_scheduler() -> BackgroundScheduler:
    global _sched
    if _sched and _sched.running:          # Rev 3.1 #6: guard reload
        return _sched

    s = BackgroundScheduler(timezone="Asia/Jakarta")

    s.add_job(_guard(check_new_emails), IntervalTrigger(minutes=5), id="email_check", **COMMON)
    s.add_job(_guard(check_sla_breaches), IntervalTrigger(minutes=5), id="sla_check", **COMMON)
    s.add_job(_guard(run_ops_check), IntervalTrigger(hours=1), id="ops_check", **COMMON)
    s.add_job(_guard(run_episode_scheduler), IntervalTrigger(minutes=1),
              id="episode_embargo", **COMMON)
    s.add_job(_guard(run_marketing_report), "cron", day_of_week="mon", hour=9,
              id="weekly_report", **COMMON)
    s.add_job(_guard(run_cache_warmer), "cron", hour=17, id="cache_warmer", **COMMON)
    s.add_job(_guard(run_recommendation_batch), "cron", day_of_week="sun", hour=22,
              id="recommendation_batch", **COMMON)
    s.add_job(_guard(cleanup_shared_context), "cron", hour=3,
              id="shared_context_cleanup", **COMMON)
    s.add_job(_guard(sweep_approvals), IntervalTrigger(hours=1), id="approval_sweep", **COMMON)
    s.add_job(_guard(check_handoffs), IntervalTrigger(minutes=15), id="handoff_check", **COMMON)
    s.add_job(_guard(backup_databases), "cron", hour=2, id="db_backup", **COMMON)
    s.add_job(_guard(run_marketing_report), "cron", day_of_week="mon", hour=9,
              id="weekly_report", **COMMON)
    s.add_job(_guard(run_cache_warmer), "cron", hour=17, id="cache_warmer", **COMMON)
    s.add_job(_guard(run_recommendation_batch), "cron", day_of_week="sun", hour=22,
              id="recommendation_batch", **COMMON)

    s.start()
    _sched = s
    _log.info("scheduler jalan: %d job", len(s.get_jobs()))
    return s


def shutdown_scheduler() -> None:
    global _sched
    if _sched and _sched.running:
        _sched.shutdown(wait=False)
    _sched = None
```

Dipasang di lifespan FastAPI:

```python
# webhook_server/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .scheduler import start_scheduler, shutdown_scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    try:
        yield
    finally:
        shutdown_scheduler()

app = FastAPI(title="Hermes Office Webhook", lifespan=lifespan)
```

---

## 4. Badan job (yang memanggil siapa)

```python
# ── Lewat Orchestrator ────────────────────────────────────────────────────
def check_new_emails():
    from hermes_bridge.agents.orchestrator import run_orchestrator
    run_orchestrator("new_email", {"source": "scheduler"})

def run_marketing_report():
    from hermes_bridge.agents.orchestrator import run_orchestrator
    run_orchestrator("weekly_analytics", {"source": "scheduler"})

def check_handoffs():
    from hermes_bridge.shared_context import SharedContext
    from hermes_bridge.agents.orchestrator import run_orchestrator
    ctx = SharedContext()
    now = time.time()
    for key, data in ctx.find("handoff:"):
        if data.get("deadline") and data["deadline"] < now:
            ctx.delete(key)          # jangan eskalasi berkali-kali
            run_orchestrator("escalate", {
                "source": "scheduler", "reason": "handoff_timeout",
                "handoff": data,
            })

# ── Internal, tidak memunculkan karakter ──────────────────────────────────
def run_ops_check():
    from hermes_bridge.agents.ops import OpsAgent
    OpsAgent().system_check()

def check_sla_breaches():
    from hermes_bridge.agents.support import SupportAgent
    SupportAgent().check_sla_breaches()

def run_episode_scheduler():
    from hermes_bridge.agents.episode_scheduler import publish_due_episodes
    publish_due_episodes()          # satu putaran, bukan loop while True

def run_marketing_report():
    # Lewat Orchestrator, seperti baris tabel §2: trigger, bukan import agent
    from . import triggers
    triggers.run_trigger("weekly_analytics", {"source": "scheduler"}, "scheduler")

def run_cache_warmer():
    from hermes_agents.cache_warmer import CacheWarmerAgent
    CacheWarmerAgent().run()

def run_recommendation_batch():
    from hermes_agents.recommendation import RecommendationAgent
    RecommendationAgent().run_batch()

def cleanup_shared_context():
    from hermes_bridge.shared_context import SharedContext
    n = SharedContext().cleanup_older_than(seconds=86400)
    _log.info("SharedContext cleanup: %d baris", n)

def sweep_approvals():
    from .approval import sweep_older_than
    n = sweep_older_than(seconds=86400)
    if n:
        _log.info("approval sweep: %d keputusan dibuang", n)

def backup_databases():
    from hermes_bridge.db import backup_all
    backup_all()
```

Perhatikan `run_episode_scheduler`: di Rev 3 ia adalah `while True` dengan `sleep(60)`. Itu salah
bentuk untuk APScheduler — satu job = satu putaran. Loop tak berujung di dalam job akan memblokir
thread scheduler dan membuat `max_instances` tidak berguna.

---

## 5. Observasi

| Apa | Di mana |
| --- | --- |
| Job terdaftar + next run | `GET /health` sidecar (tambahkan `jobs: [{id, next_run_time}]`) |
| Log job | stdout sidecar, prefix `scheduler job <name>` |
| Job yang lambat | log durasi: `_log.info("%s selesai dalam %.2fs", fn.__name__, dt)` |
| Trigger yang masuk | log satu baris per webhook: `trigger=<type> source=<source>` |

Jangan menambahkan endpoint yang mem- **trigger** job dari UI. Trigger bisnis punya dua pintu:
webhook (dengan secret) dan chat (`/design` dsb). Endpoint scheduler akan menjadi pintu ketiga yang
tidak terautentikasi dengan benar.

---

## 6. Uji

```bash
# daftar job dijalankan sekali, tanpa menunggu jam 03.00
python -c "from webhook_server.scheduler import start_scheduler; s=start_scheduler(); \
print([j.id for j in s.get_jobs()])"

# jalankan satu job manual
python -c "from webhook_server.scheduler import cleanup_shared_context; cleanup_shared_context()"

# buktikan guard reload: start dua kali, jumlah job tidak dobel
python -c "from webhook_server.scheduler import start_scheduler; \
a=start_scheduler(); b=start_scheduler(); print(len(a.get_jobs()), len(b.get_jobs()))"
```

Checklist:

- [ ] `start_scheduler()` dua kali → jumlah job sama
- [ ] `SIGTERM` sidecar → scheduler shutdown rapi (tidak ada job menggantung)
- [ ] `cleanup_shared_context` menghapus baris `ts` mundur 25 jam, bukan yang baru
- [ ] `publish_due_episodes` tidak mem-publish episode yang `status != 'scheduled'`
- [ ] `check_sla_breaches` memunculkan **satu** card per tiket, bukan dua
- [ ] Job gagal (mis. Gmail 500) tidak menghentikan job lain (lihat log putaran berikutnya)
