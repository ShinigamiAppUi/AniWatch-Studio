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
| `db_backup` | tiap hari 02.00 | `backup_databases` (DB-SCHEMA.md §13) | tidak | 300 dtk |

Catatan per job:

- **`email_check`** memakai Gmail API; kalau kredensial kosong, job hanya log sekali per jam
  (bukan tiap 5 menit) — hindari spam log.
- **`sla_check`** adalah satu-satunya job yang memunculkan permission card dari scheduler. Urutannya
  wajib: `agent_update` → `agent_waiting` → `wait_for_approval` **sekali** (fix Rev 3 #1).
- **`episode_embargo`** memeriksa `episode_schedule` tiap menit: akurasi go-live ±1 menit. Publish
  memakai `UPDATE ... WHERE status='scheduled'` (atomik) supaya DMCA tidak bisa kalah balapan.
- **`handoff_check`** memeriksa `context` key `handoff:*` yang `deadline < now`, lalu
  `run_orchestrator("escalate", {...})`; `escalate` bukan trigger webhook — hanya internal.
- **`approval_sweep`** membuang keputusan approval yang tidak pernah diambil (TTL 24 jam), supaya
  store di memori tidak tumbuh. Ini bukan pengganti timeout agent: agent tetap timeout sendiri.

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

def run_cache_warmer():
    from hermes_bridge.agents.cache_warmer import CacheWarmerAgent
    CacheWarmerAgent().run()

def run_recommendation_batch():
    from hermes_bridge.agents.recommendation import RecommendationAgent
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
