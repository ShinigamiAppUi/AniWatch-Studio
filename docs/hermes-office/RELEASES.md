# Hermes Office — Catatan Rilis

Satu entri per tag. Riwayat keputusan dokumen ada di [CHANGELOG.md](CHANGELOG.md); yang ini untuk
orang yang mau **memakai** rilisnya.

Versi `0.x` adalah versi **lapisan Hermes** (bridge, sidecar, agent) dan mengikuti minggu kerja:
`0.5.0` berarti W1–W5 selesai. `package.json` (`1.2.0`) tetap versi aplikasi kantor warisan
Claude-Office, bukan versi Hermes.

---

## v0.5.0 — 17 Nov 2026

Rilis pertama. Kantor bisa menampilkan pekerjaan agent bisnis, menerima trigger dari luar, menjawab
tiket dari knowledge base, dan angka-angkanya terlihat di UI — bukan lagi dokumen rencana.

### Yang sudah berjalan

**Pipeline episode (W3)** — satu episode dari file mentah ke `live`: Scraper → Metadata → Encoder →
Subtitle → TranslationAgent → QualityChecker → EpisodeScheduler (embargo) → Notifier + SocialMedia,
dengan DMCA cancel yang menang balapan dan penjaga duplikat. 37 cek lama di selfcheck.

**Sidecar (W4)** — `webhook_server/` sebagai FastAPI di `127.0.0.1:8765`:

- `POST /webhook` dengan `X-Webhook-Secret` (constant-time), **13 trigger** dipetakan eksplisit ke
  role, tanpa fallback `ops`; type asing → 400, secret salah → 403, selain itu `{"status":"queued"}`.
- `POST /webhook/payment` memverifikasi SHA-512 Midtrans (`order_id + status_code + gross_amount +
  key`) dan mencatat satu baris per notifikasi (`INSERT OR IGNORE`), jadi notifikasi ganda tidak
  menghasilkan refund ganda.
- Sidecar menolak start tanpa `WEBHOOK_SECRET`/`MIDTRANS_SERVER_KEY`.
- APScheduler dari lifespan: `episode_embargo` (1 menit), `sla_check` (5 menit),
  `shared_context_cleanup` (03.00), `approval_sweep` (tiap jam), `db_backup` (02.00). Enam job yang
  kerjanya belum ada didaftar di `PENDING_JOBS` dengan alasannya dan **tidak** didaftarkan.
- `GET /health` membawa `jobs`, `pending_jobs`, dan `mail`.

**Support + community (W5)**:

- `hermes_agents/kb.py`: knowledge base SQLite **FTS5** dengan 23 artikel FAQ (`kb_faq.md`), skor
  bm25 (`-rank`) dibandingkan ke `KB_MIN_SCORE`.
- `hermes_agents/support.py`: triage → cari KB → balas atau eskalasi; SLA `received_at + 1 jam`.
  `check_sla_breaches` memunculkan **satu** kartu untuk semua tiket telat, tiga opsi
  (*Handle sekarang* / *Extend SLA +30 menit* / *Close as resolved*), `wait_for_approval` sekali.
- `hermes_agents/user_report.py`: laporan user → QC (episode bermasalah), Support (akun/konten),
  atau dibuang (spam), dengan aturan duplikat 24 jam per episode.
- `hermes_agents/mailer.py`: balasan Support dikirim lewat **SMTP** (stdlib, tanpa dependensi baru).
  Setiap percobaan dicatat di `~/.hermes-office/outbox/replies.jsonl`; gagal kirim meninggalkan tiket
  `open` dengan alasannya, bukan mengaku terkirim.
- Trigger `support_ticket`, `new_email`, `user_report` menjalankan kerja agent tersebut — juga saat
  kantor tidak menyala (headless).

**UI**:

- Tombol **biz** (panel metrik bisnis: leads, email, tiket, CRM, refund, chargeback, SLA, siapa yang
  bekerja) membaca `GET /biz-metrics` dan `biz_metric_update`.
- Tombol **orch** (kartu Orchestrator): trigger yang sedang dirutekan, yang sudah lewat, katalog 13
  trigger, dan 12 handoff resmi (saat rilis ditandai `pending`; sejak Rev 3.6 chip-nya `protokol`
  karena protokol handoff sudah ada).
- Kartu approval memakai warna/emoji yang benar untuk 14 role camelCase & akronim (`PaymentAgent`,
  `SEO`, `DMCA`, …) yang sebelumnya jatuh ke default.

### Perbaikan yang ikut

- `approval.TTL_S` 6 jam → 24 jam (sesuai SCHEDULER/ARCHITECTURE/README).
- Log sidecar akhirnya muncul (`LOG_LEVEL` dipasang di lifespan; `apscheduler` diredam ke WARNING).
- `check_episode_health` menganggap episode sehat sebagai rusak (status setelah publish adalah
  `live`, bukan `published`).
- Query KB memakai `OR`, bukan AND implisit FTS5, sehingga tiket yang relevan tidak dieskalasi sia-sia.
- `GET /biz-metrics` masuk allowlist LAN full mode **dengan alasannya** (test penjaga menolak fetch
  baru yang tidak terdaftar).
- Paket `agents/` → `hermes_agents/` (bertabrakan dengan komponen plugin di root dan paket PyPI
  `agents`); satu pemuat `.env` (`hermes_bridge/env.py`) dipakai semua entry point.

### Belum ada (dan tidak dipalsukan)

| Minggu | Yang belum |
| --- | --- |
| W6 | ~~Marketing, CacheWarmer, RecommendationAgent, `weekly_report`, `cache_warmer`, `recommendation_batch`~~ — **ditutup setelah tag**, lihat CHANGELOG Rev 3.7 |
| W5 sisa | ~~`email_check`, OpsAgent, Subtitle + Moderator~~ — **ditutup setelah tag**, lihat CHANGELOG Rev 3.5 |
| W7 | ~~DesignAgent (premium)~~ — **ditutup setelah tag**, lihat CHANGELOG Rev 3.8 |
| W8 | ~~`run_orchestrator`, protokol handoff, `handoff_check`~~ — **ditutup setelah tag**, lihat CHANGELOG Rev 3.6 |
| W9 | ~~Finance, Legal, Security: refund/chargeback end-to-end, DMCA otomatis~~ — **ditutup setelah tag**, lihat CHANGELOG Rev 3.9 |
| W10 | ~~Dashboard lengkap, slash command sisanya (`/biz`, `/leads`, `/tickets`, `/sla`, `/topselling`, `/incidents`, `/unban`, `/schedule`, `/embargo`, `/translations`, `/approve-sub`, `/reports`, `/report-stats`)~~ — **ditutup setelah tag**, lihat CHANGELOG Rev 4.0. `/topselling` dan `/leads` menjawab dengan sumber data yang belum ada, bukan angka karangan |

Job yang belum ada tercatat di `GET /health` → `pending_jobs`, bukan dijalankan sebagai no-op.
Notifikasi user dan QC pipeline masih mencatat, bukan memanggil layanan luar.

> **Setelah tag v0.5.0** (Rev 3.5, commit berikutnya): sisa W5 ditutup — `Moderator`, `OpsAgent`
> (`ops_check` tiap jam), dan `email_check` yang **membaca** inbox lewat IMAP stdlib
> (`hermes_agents/inbox.py`). W8 juga ditutup (Rev 3.6): protokol handoff, `run_orchestrator`, dan
> job `handoff_check`. W6 ditutup (Rev 3.7): lima agent growth, `CacheWarmer`, laporan mingguan
> Marketing, dan tiga job terakhir — `pending_jobs` kini kosong, sebelas job berjalan. W7 ditutup
> (Rev 3.8): pipeline premium (design → QA → harga → preview → approval → live) dan tiga slash
> command pertamanya (`/design`, `/pending-items`, `/approve`) lewat `POST /command`. W9 ditutup
> (Rev 3.9): PaymentAgent + RevenueTracker (grace, refund ber-kartu, chargeback → SecOps), DMCA yang
> membatalkan lewat handoff ke EpisodeScheduler, SecOps dengan `security_incidents`, dan
> `/webhook/payment` yang benar-benar menjalankan agent — plus tujuh command finance/legal/security.
> W10 ditutup (Rev 4.0): 13 command terakhir, gauge SLA dari `first_response_at`, dan `/biz` yang
> membaca `GET /biz-metrics` milik kantor. W8 ditutup (Rev 4.1): agent Sales + Marketing, sehingga
> `new_lead`, `form_submit`, dan `deal_stage_change` menjalankan kerja dan meneruskan rantai ke
> Support. Rev 4.3 menambahkan `campaign_retry`: surat selamat datang yang gagal dikirim ulang
> dengan backoff, tanpa tiket onboarding kedua. Tag tetap menunjuk commit rilis pertama; catatan
> lengkapnya di [CHANGELOG.md](CHANGELOG.md) Rev 3.5–4.3.
>
> **Masih belum ada:** tidak ada penjualan per item, jadi `/topselling` tidak punya ranking; belum
> ada endpoint purge CDN; tidak ada integrasi CRM/Google Calendar (Sales menulis SharedContext dan
> handoff, bukan HubSpot/kalender). Semuanya disebut di jawaban command atau hasil agent yang
> bersangkutan, bukan disembunyikan.

### Cara menjalankan

```bash
# 1. Python: bridge, agent, sidecar
python3 -m venv .venv && .venv/bin/pip install httpx fastapi uvicorn apscheduler
cp .env.example .env                      # isi WEBHOOK_SECRET, MIDTRANS_SERVER_KEY, OFFICE_TOKEN

# 2. Kantor
npm install && npm run server             # http://127.0.0.1:3334 (token dicetak saat start)

# 3. Sidecar (terminal lain)
.venv/bin/uvicorn webhook_server.main:app --host 127.0.0.1 --port 8765

# 4. Satu trigger
curl -s -X POST http://127.0.0.1:8765/webhook \
  -H 'Content-Type: application/json' -H "X-Webhook-Secret: $WEBHOOK_SECRET" \
  -d '{"type":"support_ticket","data":{"subject":"Cara membatalkan langganan","email":"user@contoh.com"}}'
# Orchestrator lalu Support muncul; kalau SMTP diisi, balasan benar-benar terkirim.
```

### Verifikasi rilis ini

| Cek | Hasil |
| --- | --- |
| `python -m hermes_agents.selfcheck` | **88 PASS / 0 FAIL** |
| `npm test` (Node 22) | **73/73 file, 1631 lulus**, 16 skip |
| `python -m compileall hermes_bridge webhook_server hermes_agents` | bersih |
| CI | job `test`, `selfcheck` (Python 3.11 & 3.12), `hook-smoke` |

### Batasan yang diketahui

- **Otak agent deterministik:** tidak ada panggilan LLM/Ollama dan tidak ada LangGraph (ADR-2).
  `HERMES_MODEL`/`OLLAMA_URL` hanya cadangan yang belum dibaca kode.
- Jalur SMTP yang diuji adalah `SMTP_SECURITY=none` tanpa login; `starttls`/`ssl` + autentikasi
  memakai jalur `smtplib` standar tapi belum diuji ke provider nyata.
- Tidak ada polling email masuk, tidak ada retry otomatis untuk kiriman yang gagal (kegagalannya
  tercatat dan tiket tetap `open`, jadi kartu SLA yang menagihnya).
- Tampilan UI tidak diuji di browser pada rilis ini; yang diuji adalah data dan logika di baliknya.
- Belum ada migrasi otomatis untuk database `kb_articles` model lama: barisnya diindeks ulang ke
  `kb_articles_fts` saat pertama kali dipakai, tanpa `DROP`.
