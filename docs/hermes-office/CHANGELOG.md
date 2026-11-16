# Hermes Office — Changelog (dokumen)

Riwayat keputusan & perbaikan **dokumen**. Perubahan kode punya changelog sendiri di
`/CHANGELOG.md` (base).

---

## Rev 3.1 — 16 Nov 2026 (dokumen lengkap)

Rilis pertama yang benar-benar bisa diimplementasikan: 16 file, satu sumber per topik.

### Ditambahkan

- 16 file dokumen di `docs/hermes-office/` (sebelumnya hanya blueprint + rencana).
- [ROOMS.md](ROOMS.md): 9 ruangan (5 base + 4 lantai 2), peta 32 spot bisnis dengan id, koordinat,
  aturan navigation lewat koridor + lift.
- [AGENTS.md](AGENTS.md): config kanonik 30 role + tabel 45 agent (tools, trigger, output), kontrak
  kelas agent, cara menambah agent.
- [DB-SCHEMA.md](DB-SCHEMA.md): 12 tabel bisnis + 4 tabel base, DDL, migrasi idempoten, backup.
- [ENV-VARS.md](ENV-VARS.md): semua env var base + bisnis, `.env.example`, asal `OFFICE_TOKEN`.
- [API-REFERENCE.md](API-REFERENCE.md): endpoint base terverifikasi, endpoint bisnis, WS events,
  approval flow, 24 slash command.
- [AGENT-HANDOFFS.md](AGENT-HANDOFFS.md): SharedContext penuh, envelope handoff, tabel 12 transisi
  resmi, anti-pattern.
- [SCHEDULER.md](SCHEDULER.md): 11 job, lifespan FastAPI, guard reload, uji scheduler.
- [SECURITY.md](SECURITY.md): batas kepercayaan, binding, signature, least privilege, audit.
- [DECISIONS.md](DECISIONS.md): 12 ADR (fork, LangGraph, fire-and-forget, SQLite, format event,
  angka kebijakan, SecOps, lantai 2, approval, `.env`, dua pintu trigger, docs-first).
- [CEO-GUIDE.md](CEO-GUIDE.md): rutinitas harian, 5 jenis approval, insiden, review mingguan.
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md): 14 kelompok gejala → sebab → perbaikan.
- [PLAN.md](PLAN.md): 10 minggu dengan kriteria terima per minggu + risiko.

### Diperbaiki (dari Rev 3)

| # | Masalah | Perbaikan |
| --- | --- | --- |
| 1 | `biz-events.js` CommonJS di proyek ESM → crash | ditulis ulang ESM |
| 2 | Desk string (`biz-1`, `aw-s1`, …) tidak menunjuk spot nyata; 30 agent di 3 ruangan dev; server room 6 spot untuk 9 agent | peta ruangan dihitung ulang, spot baru berprefix `biz-*`, ruangan lantai 2 |
| 3 | `bridge._post` dipanggil dari agent | `bridge.agent_waiting()` publik |
| 4 | `queue.py` `__import__("httpx")`, token dibaca terpisah | satu konfigurasi dari `bridge.py` |
| 5 | DLQ bisa berlipat (flusher memakai `_post`) | `_send_once` + `attempts` + batas 10 |
| 6 | `start_scheduler()` saat import → job dobel saat `--reload` | dipindah ke `lifespan` + guard |
| 7 | Threshold FTS5 `0.5` dianggap pasti | env `KB_MIN_SCORE` + kewajiban kalibrasi |
| 8 | `biz_metrics` tidak cukup untuk `BizMetricsPanel` (butuh hari & gauge) | skema `(key, day)` + `GAUGE_KEYS`, bentuk respons ditetapkan |
| 9 | Jumlah 45 agent tanpa daftar tunggal | tabel tunggal di AGENTS.md (30 + 15) |
| 10 | Store approval tanpa TTL | TTL 24 jam + job `approval_sweep` |
| 11 | `run_episode_scheduler` berupa `while True` di dalam job APScheduler | jadi `publish_due_episodes()` satu putaran |
| 12 | QAAgent dan QualityChecker sama-sama 🔍 | QAAgent → ✅ |

---

## Rev 3 — 16 Nov 2026

- **Fix 1** 🔴 double `wait_for_approval` di `check_sla_breaches`.
- **Fix 2** 🟠 `update_biz_metrics` POST ke `/biz-metrics` (bukan `/event`).
- **Fix 3** 🟠 `HERMES_SIDECAR_URL` → `SIDECAR_URL`.
- **Fix 4** 🟠 webhook tidak lagi melewati Orchestrator.
- **Fix 5** 🟠 scheduler bisnis lewat Orchestrator.
- **Fix 6** 🟠 `SharedContext.cleanup_older_than()` dijadwalkan 03.00.
- **Fix 7** 🟠 guard `MIDTRANS_SERVER_KEY` saat startup.
- **Fix 8** 🟡 `MIDTRANS_SERVER_KEY` masuk tabel env.
- **Fix 9** 🟡 `hashlib.sha512` explicit `utf-8` + `.get()` default `''`.
- ➕ `TranslationAgent` 🌏 dan `UserReportAgent` 🚨 → **30 agent bisnis**.

---

## Rev 2 — 16 Nov 2026

- 🔴 5 crash: circular import DLQ, `WEBHOOK_SECRET` undefined, `update_biz_metrics` tidak ada,
  stub `run_*_agent` hilang, path schema relatif.
- 🟠 8 gap: `BUSINESS_AGENT_CONFIGS` tidak lengkap, `SocialMedia` hilang, `build_orchestrator_graph`
  tidak ada, `biz-events.js` kosong, `SharedContext` tidak thread-safe, `check_sla_breaches` tidak
  di scheduler, approval callback tidak dijelaskan, konflik nama Security.
- 🟡 7 minor: emoji Encoder bentrok, backoff tidak diimplementasi, FastAPI tidak bind 127.0.0.1,
  env var tidak lengkap, `requirements.txt` tidak ada, roadmap tidak cover agent AniWatch, ambang
  FTS5.

---

## Rev 1 — 16 Nov 2026

Blueprint pertama: konsep dua tim dalam satu kantor, fork `W17ant/Claude-Office`, daftar agent
AniWatch, arsitektur bridge Python → Express, roadmap 10 minggu.
