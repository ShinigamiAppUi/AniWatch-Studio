# Hermes Office — Changelog (dokumen)

## Rev 3.4 — 17 Nov 2026 (kanal keluar Support)

### Ditambahkan

- `hermes_agents/mailer.py`: SMTP lewat stdlib (`smtplib` + `EmailMessage`) — tanpa OAuth, tanpa
  dependensi baru. Header `From`/`Message-ID`/`Auto-Submitted: auto-replied`; `SMTP_SECURITY`
  `starttls`/`ssl`/`none`; satu percobaan = satu baris di outbox `~/.hermes-office/outbox/replies.jsonl`
  (0600), berhasil maupun gagal.
- `send_reply` kini mengirim: terkirim → tiket `pending`, counter `emails_sent` bergerak; gagal → tiket
  tetap `open`, `send_error` disimpan di context tiket, dan `handle_ticket` melaporkan `send_failed`
  (bukan `replied`).
- `GET /health` menambah `mail: {configured, last}`.
- `.env.example` + ENV-VARS.md §3b: `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USER`,
  `SMTP_PASSWORD`, `SUPPORT_FROM`, `SUPPORT_FROM_NAME`, `SMTP_TIMEOUT_S`, `HERMES_OUTBOX`.
- selfcheck 83 → **88** cek (transport injeksi: terkirim, gagal, alamat salah, outbox, tiket tetap open).

---

## Rev 3.3 — 17 Nov 2026 (W5 masuk kode)

### Ditambahkan

- `hermes_agents/kb.py` + `hermes_agents/kb_faq.md`: KB SQLite FTS5, **23 artikel** (PLAN minta 20).
  `kb_articles` kini benar-benar `CREATE VIRTUAL TABLE … USING fts5` seperti DB-SCHEMA §9 —
  database lama yang masih memakai tabel biasa diindeks ulang ke `kb_articles_fts`, tanpa DROP.
  Query dibungkus per kata dan digabung `OR`: FTS5 memperlakukan spasi sebagai AND, sehingga satu
  kata badan tiket yang tidak ada di artikel membuat tiket KB-hit tidak pernah cocok.
- `hermes_agents/support.py`: `triage_ticket`, `search_kb`, `draft_reply`, `send_reply`, `resolve`,
  `escalate`, `check_sla_breaches`. `send_reply` menulis balasan ke context tiket dan mengubah status
  ke `pending` — **tidak** mengaku sudah mengirim email (kanal keluar belum ada).
- `check_sla_breaches`: **satu** card untuk seluruh tiket telat, tiga opsi, `wait_for_approval`
  dipanggil sekali; timeout tidak mengubah apa pun sehingga putaran berikutnya menagih lagi.
- `hermes_agents/user_report.py`: triage (technical/account/spam/content), cek kesehatan episode,
  `trigger_qc_pipeline`, `forward_to_support` (membuat tiket Support sungguhan), `notify_user`
  (dicatat, kanal push belum ada), aturan duplikat 24 jam per episode.
- `webhook_server/triggers.py`: `AGENT_HANDLERS` untuk `support_ticket`/`new_email`/`user_report`;
  kerja agent jalan **juga saat headless**, dan bubble role berisi hasilnya (`replied tk-…`).
- `webhook_server/jobs.py::sla_check` terdaftar di scheduler tiap 5 menit; `sla_check` keluar dari
  `PENDING_JOBS` (tinggal 6 yang menunggu W6–W9).
- `python -m hermes_agents.selfcheck` naik 59 → **83** cek.

### Diperbaiki

- `UserReportAgent.check_episode_health` menganggap episode sehat sebagai rusak: status yang benar
  setelah publish adalah `live` (DB-SCHEMA §5), bukan `published`.


Riwayat keputusan & perbaikan **dokumen**. Perubahan kode punya changelog sendiri di
`/CHANGELOG.md` (base).

---

## Rev 3.2 — 17 Nov 2026 (W4 masuk kode)

Bukan revisi dokumen: rilis pertama di mana kode menyusul dokumennya. Sumber per topik tidak
berubah — yang berubah hanya status "belum ada" menjadi "ada".

### Ditambahkan

- `POST /webhook` (`webhook_server/triggers.py`): `X-Webhook-Secret` dibandingkan constant-time,
  13 trigger dipetakan **eksplisit** ke role (tanpa fallback `ops`), dijawab `{"status":"queued"}`;
  Orchestrator muncul lebih dulu, lalu role tujuannya. Type tak dikenal → 400.
- `POST /webhook/payment` (`payments.py`): SHA-512 `order_id + status_code + gross_amount + key`,
  `.get('')` untuk setiap field, satu baris per notifikasi (`INSERT OR IGNORE` di `payment_events`).
- Sidecar menolak start tanpa `WEBHOOK_SECRET` / `MIDTRANS_SERVER_KEY` (`triggers.require_secrets`,
  dipanggil dari lifespan).
- `webhook_server/scheduler.py` + `jobs.py`: APScheduler dipasang dari lifespan (bukan saat import),
  guard start-ganda, `max_instances=1` / `coalesce` / `misfire_grace_time`, dan 4 job yang kerjanya
  sudah ada. Tujuh job lain tercatat di `PENDING_JOBS` dengan alasan, **tidak** didaftarkan.
- `GET /health` kini memuat `jobs` dan `pending_jobs`.
- `python -m hermes_agents.selfcheck` naik 37 → 59 cek (13 trigger, signature Midtrans, dua route,
  scheduler, dan job-job-nya).
- `src/components/BizMetricsPanel.tsx` + `src/bizMetrics.ts`: tombol **biz** di status strip membuka
  angka `GET /biz-metrics` (leads, email, tiket, CRM, refund, chargeback, SLA, siapa yang bekerja);
  `biz_metric_update` memperbaruinya tanpa menunggu poll 30 detik. `GET /biz-metrics` masuk allowlist
  LAN full mode dengan alasannya.
- `src/components/OrchestratorCard.tsx` + `src/orchestrator.ts`: tombol **orch** di status strip
  menampilkan trigger yang sedang dirutekan (dari `route_trigger: <type> (<source>)`), yang sudah
  lewat, katalog 13 trigger, dan 12 handoff `AGENT-HANDOFFS.md` §3 yang ditandai **pending** karena
  `hermes_bridge/handoff.py` belum ada. Test membaca `triggers.py` dan tabel dokumen, jadi katalog
  yang melenceng (atau W8 yang mendarat tanpa status diperbarui) langsung gagal.

### Diperbaiki

| # | Masalah | Perbaikan |
| --- | --- | --- |
| 1 | `approval.TTL_S` 6 jam, sementara empat dokumen menulis 24 jam | 24 jam + `sweep()` / `sweep_older_than()` untuk `approval_sweep` |
| 2 | Log milik sidecar (`trigger=…`, `scheduler jalan`, durasi job) tidak pernah muncul karena uvicorn hanya mengatur logger-nya sendiri | `LOG_LEVEL` dipasang di lifespan; logger `apscheduler` diredam ke `WARNING` |
| 3 | Kartu approval memotong `agentId` di `-` lalu mengapitalkan, jadi 14 dari 30 role (semua camelCase + `SEO`/`DMCA`) jatuh ke warna amber dan ✋ default | `roleFromAgentId()` (`src/bizApproval.ts`) mencocokkan tabel role tanpa peduli besar-kecil huruf; test menelusuri seluruh 30 role |

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
