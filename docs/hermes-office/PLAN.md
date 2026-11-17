# Hermes Office — Roadmap Implementasi

Nov 16, 2026 · @Shin · 10 minggu, 4 fase. Setiap minggu punya **satu** deliverable yang bisa
ditunjukkan di kantor dan **satu** kriteria terima yang bisa diuji tanpa bertanya.

Aturan urutan: **jangan mulai minggu berikutnya sebelum deliverable minggu ini terlihat di UI.**
Kantor adalah alat verifikasi — kalau karakter tidak muncul, kodenya belum selesai.

---

## Fase 0 — Dokumentasi (selesai)

| Deliverable | Status |
| --- | --- |
| 16 file di `docs/hermes-office/` | ✅ Rev 3.1 |
| Config 30 role + peta ruangan konsisten | ✅ AGENTS.md, ROOMS.md |
| Schema DB terpusat | ✅ DB-SCHEMA.md |
| API + env var terpusat | ✅ API-REFERENCE.md, ENV-VARS.md |

Kriteria terima: tidak ada dua dokumen yang bertentangan soal nama role, id ruangan, nama tabel,
atau env var. Sudah diperiksa silang (lihat [DOCS-PLAN.md](DOCS-PLAN.md) §Pemeriksaan).

---

## Fase 1 — Fondasi (W1–W2)

### W1 — Base kantor hijau

- `npm install`, `npm run doctor`, `npm run install-hooks`
- `bash scripts/start-office.sh`, buka `http://127.0.0.1:3334`
- Satu sesi Claude Code muncul sebagai karakter di Main Office, jalan ke meja, selesai

**Deliverable:** kantor base jalan 100% dengan dev agent.

**Kriteria terima:** `npm test` hijau, `npm run doctor` semua green, satu agent dev terlihat
spawn → working → completed tanpa error di console browser.

### W2 — Bridge + business role

- `BUSINESS_AGENT_CONFIGS` (30 role) di `src/types.ts`
- `src/rooms.ts`: 4 `RoomId` baru + spot bisnis (ROOMS.md §5)
- `hermes_bridge/bridge.py`, `queue.py`, `shared_context.py`, `db.py`, `smoke.py`
- `webhook_server/approval.py` + `server/biz-events.js` (ESM)
- 2 baris sisipan di `server/index.js`

**Deliverable:** karakter bisnis bisa muncul di 9 ruangan dari script, dan approval card bisa
dijawab.

**Kriteria terima:**

```bash
python -m hermes_bridge.smoke --all      # 30 role muncul di meja yang benar, lalu keluar
python -m hermes_bridge.smoke --approval # card ✋ muncul; klik Allow; script lanjut
```

Card approval ikut selesai di W2: `agent_waiting` membawa `message` + `options`, kartu muncul di
panel chat (`src/bizApproval.ts`), tombolnya mengirim `approval_response` lewat WS → `biz-events.js`
→ sidecar, dan `wait_for_approval` mengambil jawabannya.

---

## Fase 2 — Pipeline AniWatch (W3–W5)

### W3 — Pipeline episode

- Scraper → Metadata → Encoder → Subtitle → **TranslationAgent** → QualityChecker →
  EpisodeScheduler → Notifier
- Schema `episode_schedule`, `subtitle_tracks` (DB-SCHEMA.md)
- Embargo queue: publish hanya kalau `status='scheduled'`, atomik

**Deliverable:** satu episode nyata jalan penuh sampai `live`.

**Kriteria terima:** dengan satu episode uji, semua 8 karakter muncul berurutan di Server Room,
episode `live` setelah embargo, dan `cancel_schedule` mencegah publish (diuji dengan DMCA palsu
sebelum embargo habis).

**Status W3:** selesai di `hermes_agents/` (`pipeline.py`, `media.py`, `episode_scheduler.py`,
`notifier.py`, `store.py`, `base.py`). Uji ulang tanpa kantor/network: `python -m hermes_agents.selfcheck`
(59 cek: `.env` terbaca dan bridge tetap inert sampai `init()`, satu episode sampai `live`, 13 trigger webhook, signature Midtrans, job scheduler, duplikat ditolak, cancel tidak pernah publish, publish tidak
mengulang, QC dua kali → `failed` + handoff). Tanpa `ffmpeg`, jalankan dengan
`HERMES_ENCODER=copy`; `encode_mode` mencatatnya, jadi tidak ada baris yang mengaku di-transcode.

### W4 — Webhook + scheduler

- FastAPI sidecar `127.0.0.1:8765`
- `SUPPORTED_TRIGGERS` + validasi secret; semua trigger lewat Orchestrator
- APScheduler: 11 job (SCHEDULER.md) — 7 inti, termasuk `cleanup_shared_context`; sisanya sweep approval, handoff check, publish embargo, dan backup

**Deliverable:** trigger dari luar (curl) memunculkan Orchestrator lalu agent yang tepat.

**Kriteria terima:** 13 trigger diuji satu per satu; tidak ada yang jatuh ke fallback `ops` kecuali
yang memang dirancang; `cleanup_shared_context` terbukti menghapus baris > 24 jam (uji dengan
`ts` mundur).

**Status W4:** sisi masuk selesai di `webhook_server/` — `triggers.py` (13 trigger dipetakan
eksplisit ke role, tanpa fallback `ops`), `payments.py` (SHA-512 + satu baris per notifikasi),
`jobs.py`, `scheduler.py`, `main.py`. `POST /webhook` menjawab 403 / 400 / `{"status":"queued"}`,
dan sidecar menolak start tanpa `WEBHOOK_SECRET` / `MIDTRANS_SERVER_KEY`. Scheduler mendaftarkan
**7 job yang kerjanya ada** — `episode_embargo`, `shared_context_cleanup`, `approval_sweep`,
`db_backup` (W4), lalu `sla_check` (W5), `email_check` dan `ops_check` (W5, `hermes_agents/inbox.py`
+ `ops.py`). Empat sisanya (`weekly_report`, `cache_warmer`, `recommendation_batch`, `handoff_check`)
tetap tercatat di `PENDING_JOBS` beserta alasannya karena agent-nya baru ada di W6/W8 — bukan
didaftarkan sebagai job kosong. Semuanya masuk `python -m hermes_agents.selfcheck` dan job CI
`selfcheck`.

### W5 — Support + Community

- [x] Support dengan KB SQLite FTS5, 23 artikel FAQ (`hermes_agents/kb.py` + `kb_faq.md`)
- [x] **UserReportAgent** (`hermes_agents/user_report.py`): triage → QC / Support / dismissed
- [x] SLA tracking + `check_sla_breaches` (satu approval untuk semua tiket telat, 3 opsi)
- [x] `sla_check` terdaftar di scheduler (tiap 5 menit) dan trigger `support_ticket` /
  `new_email` / `user_report` menjalankan kerja agent, bukan cuma menggambar karakter
- [x] Kanal keluar SMTP (`hermes_agents/mailer.py`): `send_reply` mengirim sungguhan; gagal kirim →
  tiket tetap `open`, alasan tersimpan, setiap percobaan dicatat di outbox
- [x] **Subtitle** — sudah berjalan sejak W3: `.srt`/`.ass` dibaca `parse_subtitle`, dinormalisasi
  ke UTF-8 dan ditulis sebagai `<episode>.id.srt`, baris `subtitle_tracks` dibuat `status='ready'`
- [x] **Moderator** (`hermes_agents/moderator.py`): `filter_comment` (4 aturan: piracy, abuse,
  spam, spoiler), `flag_content`, `ban_account` — setiap ban menyimpan `rule` + alasan + aktor di
  `moderation_events` yang **append-only** (SECURITY.md §10); tanpa `user_id` komentar hanya
  ditandai, tidak menggagalkan job
- [x] **OpsAgent** (`hermes_agents/ops.py`): `check_system` memeriksa disk, `PRAGMA quick_check` + ukuran
  DB, isi DLQ, baris SharedContext, job scheduler, dan kesiapan SMTP; hasilnya finding berlevel
  (`ok`/`warn`/`critical`) dengan saran tindakan, dikirim ke Discord hanya bila `DISCORD_WEBHOOK_URL` diisi
- [x] **`email_check`** (`hermes_agents/inbox.py`): IMAP stdlib (`imaplib`, `BODY.PEEK[]`), subjek
  RFC 2047 didekode, kutipan balasan dibuang, auto-reply kita sendiri (`Auto-Submitted`) dilewati,
  UID yang sudah diproses disimpan di SharedContext; kredensial kosong → log **sekali per jam**

**Deliverable:** tiket dari email/form dijawab dari KB atau dieskalasi; laporan user dirutekan.

**Kriteria terima:** laporan teknis → QC pipeline ter-trigger + user dinotif; laporan akun →
diteruskan ke Support; tiket lewat SLA memunculkan **satu** card dengan 3 opsi.

---

## Fase 3 — Growth & Product (W6–W7)

### W6 — Growth

- [x] Analytics, SEO, SocialMedia, Recommendation, Retention (`hermes_agents/analytics.py`,
  `seo.py`, `social.py`, `recommendation.py`, `retention.py`) + `growth_data.py` sebagai sumber
  angka dan `channels.py` untuk platform
- [x] SocialMedia tersambung ke akhir pipeline episode (`pipeline.announce`: Notifier → SocialMedia
  → SEO), satu post per channel per episode
- [x] Job yang menunggu W6 didaftarkan: `weekly_report` (Senin 09.00, lewat Orchestrator),
  `cache_warmer` (17.00), `recommendation_batch` (Minggu 22.00). `PENDING_JOBS` kini kosong

**Deliverable:** episode baru otomatis diumumkan ke Discord/Telegram.

**Kriteria terima:** satu episode live menghasilkan satu post Discord + satu post Telegram dalam
< 60 detik; Recommendation batch jalan Minggu 22.00 dan menulis rekomendasinya ke DB AniWatch
(di luar fork ini — fork hanya memantulkan karakternya di kantor).

**Status W6:** selesai. Yang **tidak** dipalsukan, dan itu terlihat di hasil agent:

- Angka tontonan hanya datang dari export AniWatch (`ANALYTICS_FEED`). Tanpa file itu, Analytics
  menulis snapshot data lokal dengan `source: "local"` dan daftar `insufficient`; drop-off butuh
  `views ≥ 20`, dan baris tanpa `completions` tidak dianggap nol.
- Post platform sungguhan lewat `DISCORD_WEBHOOK_URL` / `TELEGRAM_*`, satu per channel per episode
  (dedupe di SharedContext `social:<episode_id>`). X/Twitter ditandai **belum diimplementasikan**
  (bearer token hanya bisa baca), Instagram belum punya jalur API.
- `recommendation_batch` menulis ke `RECOMMENDATION_DB` kalau diisi, kalau tidak ke
  `media/published/recommendations.jsonl`; `target` di hasil menyebut yang mana.
- SEO hanya menulis file (`sitemap.xml`, `meta/`, `structured-data.json`) di folder yang sama dengan
  `feed.xml`; meng-upload ke situs bukan tugas fork ini, dan `base_url` menyebut `relative` kalau
  `SEO_SITE_URL`/`CDN_BASE_URL` kosong.
- `cache_warmer` melakukan `GET` sungguhan ke `CDN_BASE_URL`; tanpa CDN hasilnya `warmed: 0` + alasan.
- `retention_check` mengirim lewat SMTP dan hanya ke user yang id-nya alamat email (tabel
  `subscription_status` tidak punya kolom `email`); pengiriman yang sama tidak diulang dalam 7 hari.

### W7 — Premium pipeline

- [x] DesignAgent → QAAgent → PricingAgent → PreviewAgent → ✋ approval → Publisher
  (`hermes_agents/premium.py`)
- [x] `premium_items` + `/design`, `/pending-items`, `/approve` (`webhook_server/commands.py`, pintu
  `POST /command` di sidecar, relay `server/biz-events.js` → `POST /chat`)

**Deliverable:** satu item premium dari generate sampai `live` di toko.

**Kriteria terima:** Reject menghentikan pipeline, Revisi mengulang dari DesignAgent, Approve
men-deploy; approval dari card dan dari `/approve` menghasilkan status yang sama.

**Status W7:** selesai, dan yang tidak dipalsukan tertulis di hasilnya:

- **Desain dibuat di fork ini, bukan dipanggil dari model.** Tiga variasi SVG deterministik per item
  dari palet tema; context mencatat `design_source: "template"` dan, kalau `IMAGE_GEN_API_KEY`
  diisi, `image_gen: "belum diimplementasikan"`. AGENTS.md §4.5 yang lama ("berhenti di langkah
  pertama tanpa key") tidak bisa diuji di CI, jadi diganti — bukan pura-pura memanggil model.
- **QA tiga cek nyata** atas berkas yang ditulis: resolusi kanvas, warna di luar palet (tema tak
  dikenal = gagal), dan latar penuh yang menutupi transparansi. Dua kali gagal → item `rejected`
  dengan masalahnya di context.
- **Satu penulis status approval:** `premium.decide()` dipakai tombol kartu (lewat
  `request_approval` → `char.ask`) dan `/approve`; Approve langsung `publish()` (idempoten), Revisi
  kembali ke DesignAgent (maks 3 ronde), Reject berhenti. `timeout` tidak mengubah apa pun, jadi
  `/approve` masih bisa mengambilnya setelah kartu hilang.
- **Publisher menulis manifest** `media/published/premium/<id>.json` dan menyatakan
  `cdn.uploaded: false` beserta alasannya: fork ini tidak punya endpoint upload CDN yang
  terdokumentasi, dan item tidak pernah mengaku sudah di-upload.

---

## Fase 4 — Koordinasi & Bisnis (W8–W10)

### W8 — Orchestrator + handoff

- `build_orchestrator_graph()` + `route_trigger()` 13 trigger
- `SharedContext` + protocol handoff (AGENT-HANDOFFS.md)

**Deliverable:** agent bisa saling oper context, bukan hanya dipanggil Orchestrator.

**Kriteria terima:** Sales → Marketing → Support berantai tanpa kehilangan context (tiga karakter
muncul berurutan, `handoff:*` terisi lalu dibaca); pipeline episode dan rantai sales sama-sama
lulus.

**Status W8:** protokol + graph selesai di `hermes_bridge/handoff.py` dan
`hermes_agents/orchestrator.py`.

- [x] `hermes_bridge/handoff.py`: `hand_off` / `take` / `pending` / `expired` / `extend` / `drop`
  dengan **tabel transisi resmi** (12 baris AGENT-HANDOFFS.md §3). Transisi di luar tabel =
  `UnknownHandoff`; `expects` dan field payload wajib diperiksa, jadi handoff yang tidak bisa
  dikerjakan tidak pernah ditulis.
- [x] `build_orchestrator_graph()` + `run_orchestrator()`: satu node per role, `MAX_HOPS = 4`,
  mengikuti rantai dengan **mengambil** handoff (satu handoff, satu penerima). Tanpa LangGraph —
  bukan dependensi fork ini, dan graph-nya hanya jalan pendek di atas dict.
- [x] `handoff_check` (tiap 15 menit): handoff lewat `deadline` → **satu** card, tiga opsi
  (`Eskalasi ke manusia` / `Perpanjang 1 jam` / `Abaikan`).
- [x] Rantai nyata hari ini: `Support → Orchestrator` (`ticket_unresolved`). `SupportAgent.escalate`
  kini menulis handoff, `run_trigger` langsung mengikutinya, dan Orchestrator mencatat
  `escalation:<ticket>` untuk manusia — tanpa memblokir worker dengan kartu izin.
- [ ] Karakter Sales/Marketing: protocol-nya lulus di selfcheck dengan tiga node (termasuk payload
  yang berpindah), tapi **agent** Sales dan Marketing baru ada di W6 — jadi "tiga karakter muncul
  berurutan" belum bisa dibuktikan di kantor. Yang terbukti: tiga node berjalan berurutan dan
  `handoff:*` kosong lagi setelahnya.

### W9 — Finance, Legal, Security

- RevenueTracker, PaymentAgent, DMCA, SecOps
- `/webhook/payment` dengan verifikasi SHA-512

**Deliverable:** kegagalan bayar tertangani otomatis dan bisa diaudit.

**Kriteria terima:** tiga skenario PaymentAgent lulus: renewal gagal → grace 3 hari → downgrade;
refund → card → approve/tolak; chargeback → item dicabut + SecOps dinotif. DMCA membatalkan
schedule yang belum live.

**Status W9:** selesai di `hermes_agents/finance.py` (PaymentAgent + RevenueTracker),
`hermes_agents/dmca.py`, `hermes_agents/sec_ops.py` dan `POST /webhook/payment`.

- [x] `finance.py`: `handle_success` / `handle_failure` (grace 3 hari, lalu `free` +
  `subscriptions_lost`), `refund_request` (jendela 7 hari) → `request_refund_approval` (tiga opsi,
  timeout 24 jam) → `decide_refund` sebagai **satu penulis** status refund; `flag_chargeback`
  mencabut item yang disebut `item_id`, menghitung `chargebacks`, lalu handoff → SecOps.
- [x] `POST /webhook/payment` tidak lagi berhenti di `record()`: notifikasi yang baru diverifikasi
  langsung dijalankan PaymentAgent (`handle_payment_webhook`), dan handoff-nya (`payment_settled` →
  RevenueTracker, `chargeback` → SecOps) diikuti di panggilan yang sama. `refund_request` — satu-
  satunya status yang memblokir — diangkat di worker thread seperti kartu premium.
- [x] `dmca.py`: verifikasi (`episode_id`, `requester`, `reason`) → catat di `dmca_requests` →
  handoff `DMCA → EpisodeScheduler` (baris §3) → node EpisodeScheduler memanggil `cancel_schedule`
  (belum live) atau unpublish (sudah live). Permintaan yang lewat jendela/payload tidak lengkap
  tetap dicatat sebagai `refused`; purge CDN tidak diklaim (belum ada endpoint).
- [x] `sec_ops.py`: empat rule AGENTS §4.6; `login_attempts`/`concurrent_devices`/`request_rate`
  hanya jalan dengan `SECURITY_EVENT_FEED` (dan `insufficient` menyebutnya kalau kosong),
  `chargeback_count` dibaca dari `payment_events`; aksi dicatat append-only di
  `security_incidents`, `/unban` menambah baris. `agent_working` hanya saat ada pelanggaran.
- [x] `/revenue`, `/payments`, `/subscriptions`, `/refunds`, `/chargeback`, `/security`,
  `/takedown` didaftarkan di `webhook_server/commands.py` + relay chat.
- [x] Tidak ada job scheduler baru: kesebelas job SCHEDULER.md §2 sudah terdaftar sejak W6, dan W9
  bekerja dari event (webhook) serta command, bukan dari putaran berkala.

### W10 — Dashboard + polish

- [x] `BizMetricsPanel.tsx` — ada: tombol **biz** di status strip, `GET /biz-metrics` +
  `biz_metric_update` (`src/bizMetrics.ts`, 8 test di `tests/biz-metrics-ui.test.ts`)
- [x] `OrchestratorCard.tsx` — ada: tombol **orch** di status strip, menampilkan trigger yang
  sedang dirutekan, trigger yang sudah lewat, 13 trigger yang bisa dirutekan, dan 12 handoff
  `pending` (`src/orchestrator.ts`). `build_orchestrator_graph()` di Python tetap W8.
- [x] SLA + metrics live: tiket mencatat `first_response_at` (balasan terkirim pertama) dan
  Support mengirim gauge `tickets_pending`, `tickets_resolved`, `sla_avg_response_min`,
  `sla_breach_count` setiap kali tiket berubah. Kolomnya masuk lewat `migrate()`, bukan DROP.
- [x] Semua slash command terdaftar (23): `/biz`, `/leads`, `/tickets`, `/sla`, `/topselling`,
  `/incidents`, `/unban`, `/schedule`, `/embargo`, `/translations`, `/approve-sub`, `/reports`,
  `/report-stats` menyusul tujuh command W9. `/cancel-schedule` tidak didaftarkan: `/takedown`
  adalah pintunya, dengan audit DMCA.
- [x] CacheWarmer + Retention scheduler aktif sejak W6 (`cache_warmer` 17.00, `weekly_report`
  Senin 09.00 lewat Orchestrator); W10 tidak menambah job.
- [x] Backup harian `db_backup` 02.00 (DB-SCHEMA.md §13), terdaftar sejak W4.

**Deliverable:** kantor siap dipakai harian oleh CEO.

**Kriteria terima:** checklist [BLUEPRINT.md](BLUEPRINT.md) §11 dicentang semua, dan satu hari
operasional penuh (pagi analytics → siang episode → malam report) berjalan tanpa campur tangan
manual kecuali approval.

**Status W10:** selesai, dengan tiga batas yang ditulis di jawaban command-nya sendiri:

- **`/biz` membaca kantor, bukan menebak.** Counter hidup di `chat.db` dan ditulis
  `server/biz-events.js`; sidecar memanggil `GET /biz-metrics`. Kantor yang mati dijawab "kantor
  tidak menjawab" beserta alasannya, bukan laporan kosong yang terlihat seperti hari sepi.
- **`/topselling` tidak punya sumber data.** `payment_events` tidak menyimpan `item_id` dan
  `premium_items` tidak punya kolom penjualan, jadi command menyebutkan itu dan hanya melaporkan
  jumlah item live/dicabut. Mengurutkan item berdasarkan harga lalu menyebutnya "terlaris" akan jadi
  satu-satunya laporan palsu di kantor.
- **`/leads` bergantung pada agent Sales yang belum ada** (W8 di atas). Command membaca `lead:*` di
  SharedContext dan, bila kosong, mengatakan bahwa agent-nya belum ada.

**Verifikasi W10:** selfcheck **193 PASS / 0 FAIL** (17 cek W10: SLA dari respons pertama, migrasi
kolom lama, `/biz` lewat HTTP sungguhan + kantor mati, satu lead nyata, `/topselling` jujur, insiden
+ unban append-only, schedule/embargo, translations/approve-sub, reports/report-stats, dan 23
command yang semuanya menjawab `handled`).

---

## Graf dependensi

```
                    ┌──▶ W3 (pipeline episode) ──┐
                    │                            │
W1 ──▶ W2 ──────────┼──▶ W4 (webhook+scheduler) ──┼──▶ W8 ──▶ W9 ──▶ W10
 (base)  (bridge)    │                            │   (orkestrasi) (uang)  (dashboard)
                    ├──▶ W5 (support+community) ─┘
                    │
                    └──▶ W6 ──▶ W7
                        (growth) (premium)
```

| Aturan | Alasannya |
| --- | --- |
| W2 menunggu W1 | bridge butuh kantor yang benar-benar menerima event |
| W3, W4, W5 boleh paralel setelah W2 | ketiganya hanya butuh config + bridge |
| W6 boleh mulai setelah W2, tidak perlu W3 | growth memakai data AniWatch, bukan pipeline baru |
| W7 (premium) setelah W6 | DesignAgent memakai tool image-gen yang sama dengan growth content |
| W8 menunggu W3 **dan** W5 | menguji dua rantai handoff: pipeline dan sales→support |
| W9 setelah W8 | chargeback butuh `run_orchestrator` yang sudah stabil |
| W10 menunggu semuanya | panel metrics membaca semua angka yang dihasilkan W3–W9 |

**Risiko jalur kritis:** W3 → W4 → W5 → W8 → W9 → W10. Kalau waktu mepet, W6 dan W7 yang dipotong
dulu — keduanya tidak memblokir operasional harian.

---

## Risiko & mitigasi

| Risiko | Dampak | Mitigasi |
| --- | --- | --- |
| Hermes/Ollama lambat atau tidak tersedia | agent menggantung, kantor terlihat sibuk tanpa hasil | timeout LLM per langkah (60 dtk) + fallback deterministik untuk langkah non-LLM |
| 30 karakter berdesakan | UI berat, sulit dibaca | batas aktif bersamaan 12 (Orchestrator antri sisanya); spot sudah disebar 5 ruangan |
| Event storm dari loop SecOps | ribuan `agent_working` | SecOps hanya mengirim event saat **ada** pelanggaran, bukan tiap 10 dtk |
| Approval ditinggal | pipeline menggantung | timeout per task (300 dtk default) + eskalasi ke antrian manusia |
| Threshold KB salah | Support menjawab salah atau terlalu sering eskalasi | kalibrasi dengan 20+ artikel, ukur presisi sebelum produksi |
| Token di-rotate | semua event 401 → DLQ | dokumentasi ENV-VARS.md §OFFICE_TOKEN, restart bridge setelah rotate |

---

## Definition of done (berlaku semua minggu)

- [ ] Terlihat di kantor (bukan hanya log)
- [ ] `npm test` hijau
- [ ] `python -m compileall hermes_bridge webhook_server hermes_agents` bersih
- [ ] `python -m hermes_agents.selfcheck` hijau (CI menjalankannya: job `selfcheck`, Python 3.11 dan 3.12)
- [ ] Tidak ada `except: pass` baru
- [ ] Env baru tercatat di ENV-VARS.md, tabel baru di DB-SCHEMA.md, endpoint baru di API-REFERENCE.md
- [ ] Satu baris di CHANGELOG.md
