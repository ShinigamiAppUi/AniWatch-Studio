# Hermes Office — Changelog (dokumen)

## Rev 4.6 — 18 Nov 2026 (narasi otak agent diselaraskan dengan kode)

### Diubah

- Semua dokumen yang menjanjikan **LLM Hermes** (`nous-hermes-2` via Ollama) dan/atau **LangGraph**
  kini menyatakan yang sebenarnya: agent bisnis **deterministik** (aturan + SQLite + HTTP), LLM dan
  LangGraph **belum diimplementasikan**, dan tidak ada env var LLM yang dibaca kode. Tersentuh:
  README (ringkasan, diagram, tabel perbedaan, Requirements, prinsip 3), ARCHITECTURE (§1 diagram,
  §2 port, §3 tech stack, §6 alur, §7 kegagalan), BLUEPRINT (§1 dan alur §8), DECISIONS **ADR-2**
  (ditulis ulang), ENV-VARS (§2 tabel + contoh), SECURITY §3, PLAN (tabel risiko), DOCS-PLAN
  (baris pemeriksaan), AGENTS §5, AGENT-HANDOFFS §6.
- `requirements.txt`: `langgraph` dihapus — tidak pernah di-import; Orchestrator adalah graph di
  atas `dict` (`hermes_agents/orchestrator.py`). Tidak ada kode yang berubah.
- `.env.example` dan ENV-VARS: `HERMES_MODEL` dan `OLLAMA_URL` ditandai **cadangan** dan
  dikomentari, karena tidak ada yang membacanya.
- README: jumlah agent bisnis 30 → **31** (5 generic + 26 AniWatch, sesudah role `Resolver`).

### Batas

- Ini perbaikan dokumentasi, bukan penambahan LLM. Kalau otak Hermes diinginkan, itu pekerjaan baru
  (client Ollama + timeout + fallback) dan ADR-2 yang berlaku hari ini harus diganti lebih dulu.

---

## Rev 4.5 — 17 Nov 2026 (W11d: Scraper tersambung, role Resolver)

### Ditambah

- `hermes_agents/aniwatch_admin.py`: satu pintu ke admin API AniWatch (`ANIWATCH_API_URL` +
  `ANIWATCH_ADMIN_TOKEN`, ENV-VARS §3f). Tanpa keduanya setiap panggilan mengembalikan `ok: false` +
  alasan, bukan daftar kosong yang terbaca sebagai "semua sehat".
- `hermes_agents/scraper.py`: `backfill()`, `run_target()`, `queue_summary()`, `sources_health()`,
  `propose_domain()`. Role ini tidak mengikis situs sendiri; `propose_domain()` mengirim kartu
  approval berisi bukti dan **tidak** memanggil PATCH `baseurl` (W11 §8).
- `hermes_agents/resolver.py`: `resolve()` (dry run `POST /v1/admin/media/resolve`), `refresh_due()`
  (membaca `need_direct` dari SharedContext, mengembalikan `direct_ready` + `expires_at`, menghitung
  host `host_not_supported`), dan `health_report()`. Tidak ada URL putar yang disimpan (D-64).
- Role `Resolver` (`🔗`, `biz-s10`, server room) di `src/types.ts`, plus spot + waypoint `biz-s10` di
  `src/rooms.ts`. Role bisnis 30 → 31, total agent 45 → 46.
- Tiga job scheduler: `source_health` (30 menit), `scraper_backfill` (tiap jam), `resolver_refresh`
  (6 jam). Total job 12 → 15.
- Tiga slash command: `/scrape [source|episode]`, `/resolver`, `/sources` (23 → 26), di
  `webhook_server/commands.py` dan `server/biz-events.js`.
- Selfcheck: **224 PASS / 0 FAIL** (7 cek W11d: tanpa variabel → `ok: false`, `/sources` per content
  type, `/scrape` + filter per item, `backfill` mengirim `SCRAPER_BACKFILL_BATCH`, `direct_ready` +
  host tanpa adapter, `/resolver`, dan `propose_domain` yang tidak menulis apa pun).

### Diubah

- `tests/businessAgents.test.ts` (31 meja unik), `tests/rooms.test.ts` (sepuluh meja Core Ops),
  `tests/biz-commands.test.ts` (26 command).
- AGENTS §4.2 (10 role Core Ops + kartu Resolver), ROOMS §5.2/§6, SCHEDULER §2 (15 job),
  API-REFERENCE §6, ENV-VARS §3f + `.env.example`.

### Batas

- W11a–W11c belum ada: factory, `adapters_gen.go`, runner, `PageResolver`, antrean `000020`, dan
  endpoint §4.7 masih di repo AniWatch. Selama itu ketiga command menjawab alasan yang jelas, bukan
  angka; `refresh_due()` baru punya pekerjaan setelah `GET /v1/admin/scrape/queue` dan
  `POST /v1/admin/media/resolve` hidup.
- Health job kantor **tidak** menulis `is_active` maupun `base_url`: keduanya milik backend (§3 satu
  field satu penulis).

---

## Rev 4.4 — 17 Nov 2026 (surat yang menyerah terlihat di chat)

### Ditambah

- `hermes_agents/marketing.py` `gave_up_campaigns()`: membaca `campaign:*` yang `sent: false` dan
  `attempts` sudah mencapai `MAX_WELCOME_ATTEMPTS`, mengembalikan `lead`, `email`, `attempts`,
  `last_error`, dan `last_at`. Catatan tidak diubah — fungsi ini hanya membaca.
- `webhook_server/commands.py`: satu baris `⚠️ Surat selamat datang menyerah (N): <lead>` di `/leads`
  (field `campaigns_gave_up`) dan di `/biz` (field `campaigns_gave_up`). Baris itu dibaca dari DB
  sidecar sendiri, sehingga `/biz` tetap melaporkannya saat `GET /biz-metrics` gagal.
- Selfcheck: **217 PASS / 0 FAIL** (4 cek baru: surat berhenti setelah empat percobaan + error
  terakhir tersimpan, `gave_up_campaigns()` mengembalikan lead yang tepat, `/leads` menyebut lead
  itu dalam batas 6 baris, `/biz` menyebutnya tanpa kantor berjalan).

### Diubah

- `/leads` memprioritaskan baris campaign di atas catatan "…dan N lead lain hari ini" saat pesan
  mencapai 6 baris; daftar lead hari ini tetap dua baris.
- API-REFERENCE §6 (`/biz`, `/leads` + catatan), AGENTS §4.1 Marketing, DB-SCHEMA §11 disinkronkan.

### Batas

- Baris ini melaporkan kegagalan yang sudah berhenti, bukan yang masih menunggu backoff — yang
  menunggu memang belum menjadi masalah manusia. Tidak ada tombol kirim ulang manual: setelah
  empat percobaan, memperbaiki `SMTP_HOST` lalu menunggu konversi berikutnya adalah jalannya.

---

## Rev 4.3 — 17 Nov 2026 (retry surat selamat datang)

### Ditambah

- `hermes_agents/marketing.py` `retry_welcome()`: mengirim ulang surat selamat datang yang percobaan
  pertamanya gagal (`sent: false`). Sumber kebenarannya catatan `campaign:<lead>`; jeda 15 → 30 →
  60 menit (`WELCOME_RETRY_S`), maksimal `MAX_WELCOME_ATTEMPTS = 4` percobaan. Fungsi ini **hanya**
  menulis ulang catatan — tidak menulis handoff, jadi tiket onboarding tetap satu per lead.
- Job scheduler `campaign_retry` (tiap 15 menit) → `webhook_server/jobs.retry_welcome_campaigns`.
  Total job menjadi dua belas; `PENDING_JOBS` tetap kosong karena kerjanya ada.
- Catatan `campaign:<lead>` menyimpan `name`, `last_at`, `sent_at`, `handoff`, `next_try_at`, dan
  `last_error` supaya surat ulangan memakai isi yang sama dan alasannya bisa dibaca.

### Diubah

- Konversi kedua untuk lead yang suratnya belum terkirim menjawab `duplicate` + `retry_at` (bukan
  mengirim langsung): burst konversi tidak boleh menjadi burst email. Pengiriman ulang tetap milik
  job, dengan backoff.
- Selfcheck: **213 PASS / 0 FAIL** (3 cek retry: menunggu backoff, mengirim tanpa tiket kedua,
  tidak mengulang surat yang sudah keluar; cek jumlah job scheduler jadi 12).
- SCHEDULER.md §2 (baris + catatan + hitungan), AGENTS §4.1 Marketing, DB-SCHEMA §11, PLAN W8/W9,
  RELEASES, DOCS-PLAN disinkronkan.

### Batas

- Retry tetap butuh `SMTP_HOST`; tanpa itu ia berhenti setelah empat percobaan dengan `sent: false`
  dan alasan `SMTP belum dikonfigurasi`, bukan mengklaim terkirim.

---

## Rev 4.2 — 17 Nov 2026 (`/leads` sebagai pipeline)

### Diubah

- `webhook_server/commands.py` `/leads`: kini menjawab tiga hal sekaligus dan menyebut jendela
  masing-masing — pipeline per stage dari **semua** `lead:*` (deal yang menang minggu lalu tetap
  `won`, jadi tidak dilabeli "hari ini"), jumlah lead yang masuk hari ini beserta dua terbaru
  (tahap + skor), dan handoff ber-subject `lead:` yang belum diambil dikelompokkan per rute
  (`Sales→Marketing`, `Marketing→Support`). Respons membawa `pipeline`, `handoffs`, `waiting`.
- Selfcheck: **210 PASS / 0 FAIL** (2 cek baru: hitungan per stage + handoff tertunda tampil;
  handoff yang di-drop hilang dari tampilan).
- API-REFERENCE §6 dan PLAN W10 diperbarui; tidak ada command baru (tetap 23).

### Catatan

- "Tertunda" berarti handoff yang masih ada di SharedContext; yang sudah diambil penerima tidak
  dihitung dua kali, karena `take()` menghapusnya (AGENT-HANDOFFS §5.1).

---

## Rev 4.1 — 17 Nov 2026 (W8 sisa: agent Sales + Marketing)

### Ditambahkan

- `hermes_agents/sales.py`: SalesAgent dengan tiga trigger yang sebelumnya hanya menggambar karakter
  — `new_lead`, `form_submit`, `deal_stage_change`. `qualify_lead()` memberi skor 0..1 dari payload
  saja dengan satu alasan per poin (`{rule, points, detail}`), ambang `QUALIFY_MIN_SCORE = 0.5`;
  `update_crm()` menulis `lead:<id>` di SharedContext (bukan HubSpot); `send_email()` lewat SMTP
  `mailer` yang sama dengan Support; `schedule_meeting()` hanya menulis handoff (tidak ada kalender).
  Form ganda = `duplicate` tanpa surat/handoff kedua; `meeting` tanpa `when`+`timezone` ditolak utuh;
  `closed_won`/`demo` dipetakan ke stage resmi, stage asing ditolak beserta daftarnya.
- `hermes_agents/marketing.py`: `onboard_lead()` — node untuk handoff `lead_converted`: satu surat
  selamat datang, catatan `campaign:<lead>`, lalu handoff `customer_onboarding` ke Support. Konversi
  kedua menjawab `duplicate`; surat yang gagal menyimpan alasannya dan tetap diteruskan ke Support.
- `hermes_agents/support.py`: `receive_handoff()` — `onboarding_followup` menjadi tiket nyata
  (`channel='onboarding'`), `pre_meeting_brief` menjadi `brief:<lead>`.
- `hermes_agents/orchestrator.py`: node `Sales`, node `Marketing` (kampanye vs laporan mingguan
  dibedakan lewat `expects`), dan node `Support` yang membedakan handoff dari trigger.

### Diubah

- `webhook_server/triggers.py`: `AGENT_HANDLERS` memetakan `new_lead`/`form_submit`/
  `deal_stage_change` ke `_sales_work`; bubble menyebut id lead. Komentar "agent Sales belum ada"
  dihapus karena agent-nya sekarang ada.
- `/leads` menampilkan tahap + skor dan, untuk hari kosong, menyebut trigger yang menulis `lead:*`
  (bukan lagi "agent belum ada").
- Selfcheck: **208 PASS / 0 FAIL** (15 cek baru — rantai Sales → Marketing → Support pada agent
  sungguhan, form ganda, lead lemah tidak di-handoff, meeting + brief, konversi kedua tanpa surat
  kedua, penolakan stage/lead tak dikenal, jalur `run_trigger` headless, dan wiring ketiga trigger).
- PLAN W8 (checkbox karakter + status), AGENTS §4.1 (kartu Sales + Marketing), AGENT-HANDOFFS §7/§8,
  API-REFERENCE §4/§6, DB-SCHEMA §11 diperbarui dalam commit yang sama.

### Catatan

- Tidak ada integrasi yang dipalsukan: `HUBSPOT_API_KEY` tidak dibaca, `GOOGLE_*` tidak dipakai,
  dan tanpa `SMTP_HOST` surat Sales/Marketing pulang sebagai `sent: false` beserta alasannya.

---

## Rev 4.0 — 17 Nov 2026 (W10: dashboard, SLA live, sisa slash command)

### Ditambahkan

- `webhook_server/commands.py`: 13 command terakhir API-REFERENCE §6 — `/biz`, `/leads`, `/tickets`,
  `/sla`, `/topselling`, `/incidents`, `/unban`, `/schedule`, `/embargo`, `/translations`,
  `/approve-sub`, `/reports`, `/report-stats` (total 23). Semuanya menjawab dari baris DB yang sama
  yang ditulis agent, satu pesan maksimal enam baris.
- `hermes_agents/support.py`: `sla_stats()` — compliance tiket selesai 7 hari, tiket lewat deadline,
  rata-rata respons pertama beserta jumlah sampel. `send_reply()` mengisi `first_response_at`
  sekali (`COALESCE`), dan gauge `tickets_pending` / `tickets_resolved` / `sla_avg_response_min` /
  `sla_breach_count` dikirim setiap kali tiket berubah, jadi panel **biz** bergerak.
- `hermes_bridge/bridge.py`: `get_biz_metrics()` — `/biz` membaca `GET /biz-metrics` milik kantor
  (counter hidup di `chat.db`), dan kantor yang mati dijawab sebagai kantor yang mati.
- `hermes_bridge/shared_context.py`: `recent(prefix, since)` — `/leads` butuh timestamp, bukan hanya
  nilai; `find()` tetap dipakai handoff.
- `tickets.first_response_at` di `schema_biz.sql`, dan `db.migrate()` menambahkannya ke DB lama
  tanpa DROP (selfcheck W10 menguji tabel versi lama).
- `/unban` menulis baris `unban` baru ke `security_incidents` (append-only, SECURITY §10).

### Diubah

- `server/biz-events.js`: `BIZ_SLASH_COMMANDS` + regex relai kini 23 command; `tests/biz-commands.test.ts`
  memeriksa daftarnya dan bahwa `/unbanned`/`/slack` tetap pesan biasa.
- Selfcheck: **193 PASS / 0 FAIL** (17 cek W10: SLA dari respons pertama, migrasi kolom lama,
  `/biz` lewat HTTP sungguhan + kantor mati, satu lead nyata di SharedContext, `/topselling` yang
  menyebut sumber data hilang, insiden + unban append-only, schedule/embargo, translations/approve-sub,
  reports/report-stats, dan 23 command yang semuanya `handled`).
- Komentar `webhook_server/triggers.py` tidak lagi bilang agent Sales datang "di W10": agent itu
  belum ada (PLAN.md W8), dan `/leads` mengatakan hal yang sama ke pengguna.
- Docstring panel/metrics: `biz_metric_update` dibroadcast **kantor**, bukan sidecar.
- API-REFERENCE §6, DB-SCHEMA §2/§3/§12, AGENTS §4.1, SCHEDULER, PLAN W10 dan RELEASES diperbarui
  dalam commit yang sama.

### Catatan

- Panel `BizMetricsPanel` dan `OrchestratorCard` sudah ada sebelum W10; yang W10 kerjakan adalah
  membuat angkanya hidup dan sisa pintu chat-nya nyata. `/topselling` tidak mengurutkan item
  berdasarkan harga lalu menyebutnya terlaris: penjualan per item tidak tercatat.

---

## Rev 3.9 — 17 Nov 2026 (W9: Finance, Legal, Security)

### Ditambahkan

- `hermes_agents/finance.py`: PaymentAgent + RevenueTracker. Renewal gagal → grace 3 hari (+ surat
  saran metode lain) → `free` + `subscriptions_lost`; refund hanya di dalam jendela 7 hari, kartu
  Approve/Tolak/Minta Info (timeout 24 jam) dengan `decide_refund()` sebagai satu-satunya penulis;
  chargeback mencabut item yang disebut `item_id`, menghitung `chargebacks`, lalu handoff → SecOps;
  snapshot revenue harian ke `media/published/revenue/YYYY-MM-DD.json` dengan dua aturan anomali
  (`refund_rate > 20%` hanya bila ≥ 5 order, `chargebacks ≥ 2`).
- `hermes_agents/dmca.py`: verifikasi (`episode_id`, `requester`, `reason`) → `dmca_requests` →
  handoff `DMCA → EpisodeScheduler` → `cancel_schedule` (belum live) atau unpublish (sudah live).
  `cdn_purged: false` beserta alasannya; takedown per anime ditolak dan tetap tercatat.
- `hermes_agents/sec_ops.py`: empat rule AGENTS §4.6, `security_incidents` append-only, `/unban`
  sebagai baris baru. Tanpa `SECURITY_EVENT_FEED` tiga rule request tidak berjalan dan hasilnya
  menyebut variabel itu; `chargeback_count` tetap jalan dari `payment_events`.
- Trigger `chargeback_received` kini punya kerja agent (`finance.handle_trigger`), dan graph
  Orchestrator memuat node `PaymentAgent`, `RevenueTracker`, `SecOps`, `EpisodeScheduler` — penerima
  handoff ikut jadi node, jadi rantai uang dan takedown terlihat sebagai hop, bukan catatan di kode.
- `POST /webhook/payment` tidak lagi berhenti di `record()`: PaymentAgent dijalankan setelah signature
  + baris idempoten, handoff-nya diikuti, dan jawabannya menyebut `action` yang terjadi.
  `transaction_status: "refund_request"` adalah pintu permintaan refund (satu-satunya yang memblokir,
  diangkat di worker thread).
- `webhook_server/commands.py`: `/revenue`, `/payments`, `/subscriptions`, `/refunds`, `/chargeback`,
  `/security`, `/takedown`, direlai `server/biz-events.js` (10 command bisnis).
- `hermes_bridge/schema_biz.sql` + DB-SCHEMA §16/§17: `security_incidents`, `dmca_requests`;
  `premium_items.status` mendapat nilai `revoked`.
- `SECURITY_EVENT_FEED` di ENV-VARS §3e dan `.env.example`.

### Diubah

- Selfcheck: **176 PASS / 0 FAIL** (22 cek W9: grace, downgrade, refund approve/tolak/timeout/
  jendela, chargeback + revoke + hop SecOps, feed hilang vs feed ada, cooldown, unban, takedown
  scheduled/live/duplikat/ditolak, `POST /webhook/payment` end-to-end, tiga command, node graph).
- `tests/biz-commands.test.ts`: daftar command bisnis kini sepuluh.
- API-REFERENCE §4/§6, AGENTS §4.6, DB-SCHEMA §7/§8/§16/§17, SECURITY §7/§10, PLAN W9, ENV-VARS §3e
  diperbarui dalam commit yang sama.

---

## Rev 3.8 — 17 Nov 2026 (W7: premium pipeline)

### Ditambahkan

- `hermes_agents/premium.py`: pipeline `draft → qa_passed → priced → previewed → pending_approval →
  approved → live`. Tiga variasi SVG deterministik per item (palet tema `neon`/`sakura`/`ocean`),
  `design_source: "template"`; QA tiga cek nyata (resolusi, warna di luar palet, transparansi) dengan
  satu kesempatan desain ulang lalu `rejected`; harga dari tabel `TIERS` atas jumlah elemen;
  `preview-light.svg`/`preview-dark.svg`.
- `premium.decide()` sebagai **satu penulis** status approval, dipakai tombol kartu
  (`request_approval` → `char.ask`, timeout 24 jam) dan `/approve`; `publish()` idempoten dan menulis
  manifest `media/published/premium/<id>.json` dengan `cdn.uploaded: false` + alasannya.
- `webhook_server/commands.py` + `POST /command` di sidecar: `/design`, `/pending-items`,
  `/approve` dengan balasan satu pesan chat (maks 6 baris).
- `server/biz-events.js`: `bizSlashCommand()` merelai baris itu ke sidecar; `POST /chat` di
  `server/index.js` kini `async` dan memakai relay tersebut setelah command base tidak cocok.
- `tests/biz-commands.test.ts`: 8 test relay (hanya tiga command, command base tidak direlai,
  sidecar mati → pesan menyebut command, baris panjang di-clamp).

### Diubah

- Dokumen yang sebelumnya menjanjikan image model di DesignAgent kini menyatakan yang sebenarnya:
  fork tidak memanggil provider image-gen (ENV-VARS §3, AGENTS §4.5, PLAN W7).
- Selfcheck: **154 PASS / 0 FAIL** (15 cek W7: /design, /pending-items, /approve, kartu, Reject,
  Revisi, timeout, manifest, publish ganda, route `/command`).
- API-REFERENCE §4/§6, DB-SCHEMA §8, SECURITY §4.2, PLAN W7 ikut diperbarui dalam commit yang sama.

---

## Rev 3.7 — 17 Nov 2026 (W6: growth)

### Ditambahkan

- `hermes_agents/growth_data.py`: satu sumber angka growth dengan **dua sumber yang selalu disebut** —
  export AniWatch (`ANALYTICS_FEED`: `episodes` + `history`) dan DB fork ini (`episode_schedule`,
  `tickets`, `user_reports`). Drop-off hanya dihitung kalau `views ≥ 20` dan penyelesaian < 50%;
  baris tanpa metrik dilewati, bukan dianggap nol.
- `hermes_agents/analytics.py` (📊 `analytics_ready`): snapshot `media/published/analytics/<tanggal>.json`.
  Tanpa export: `source: "local"` + `insufficient` yang menyebut apa yang belum bisa dihitung.
- `hermes_agents/seo.py` (🔎 akhir pipeline): `meta/<episode>.json`, `sitemap.xml` (hanya
  `status='live'`) dan `structured-data.json` (JSON-LD `TVEpisode`), dengan `base_url` jujur
  (`SEO_SITE_URL` → `CDN_BASE_URL` → `relative`).
- `hermes_agents/social.py` + `channels.py` (📱 akhir pipeline, `announce_episode`,
  `content_schedule`): satu post per channel per episode, `{posted, reason}` per platform, dedupe di
  SharedContext `social:<episode_id>`. X/Twitter ditandai belum diimplementasikan, bukan didiamkan.
- `hermes_agents/recommendation.py` (🎯 Minggu 22.00): model co-view, tulis ke `RECOMMENDATION_DB`
  (tabel `recommendations`) kalau diisi, kalau tidak ke `media/published/recommendations.jsonl`.
- `hermes_agents/retention.py` (💌 `retention_check`): segmen `subscription_status` (kedaluwarsa /
  masa tenggang), surat lewat SMTP, cooldown 7 hari per user, user tanpa alamat email dilewati.
- `hermes_agents/cache_warmer.py` (⚡ 17.00): `GET` sungguhan per file episode live ke `CDN_BASE_URL`;
  tanpa CDN → `warmed: 0` + alasan.
- `hermes_agents/marketing.py` (📣 `weekly_analytics`): laporan mingguan
  `media/published/reports/weekly-<ISO week>.md` + ringkasan Discord.

### Diubah

- `pipeline.announce` menjalankan **tiga** karakter: Notifier (feed + `notifications.jsonl`),
  SocialMedia (satu post per channel), SEO (meta + sitemap). `notifier.notify()` tidak lagi mem-posting
  channel — itu yang membuat satu episode tidak diumumkan dua kali; `notified_channels` dan
  `notified_skipped` kini diisi dari hasil SocialMedia.
- `webhook_server/triggers.py`: `AGENT_HANDLERS` menambah `analytics_ready`, `weekly_analytics`,
  `content_schedule`, `announce_episode`, `retention_check`. Sisa yang hanya menggambar karakter:
  trigger Sales (agent-nya belum ada).
- Scheduler: **11 job** hidup (tambah `weekly_report`, `cache_warmer`, `recommendation_batch`),
  `PENDING_JOBS` **kosong**.
- ENV-VARS.md §3d + `.env.example`: `ANALYTICS_FEED`, `RECOMMENDATION_DB`, `SEO_SITE_URL`.
- DB-SCHEMA.md §15: file growth + tabel `recommendations` milik AniWatch (di luar DB fork).
- Selfcheck: **139 PASS / 0 FAIL** (25 cek W6 baru).

---

## Rev 3.6 — 17 Nov 2026 (W8: Orchestrator + handoff)

### Ditambahkan

- `hermes_bridge/handoff.py`: protokol handoff dengan **tabel transisi resmi** (12 baris
  AGENT-HANDOFFS.md §3). `hand_off` menolak transisi di luar tabel (`UnknownHandoff`), `expects`
  yang tidak cocok, dan payload yang kurang field; `take` hanya untuk role yang dituju dan sekali
  pakai; `expired` / `extend` / `drop` untuk job `handoff_check`.
- `hermes_agents/orchestrator.py`: `build_orchestrator_graph()` (node per role, `MAX_HOPS = 4`,
  role tanpa agent = `skipped`), `run_orchestrator()`, `follow_chain()`, `escalate_to_human()`,
  `graph_summary()`. Tanpa LangGraph: graph-nya jalan pendek di atas dict, bukan state machine.
- Job `handoff_check` (tiap 15 menit): handoff lewat `deadline` → **satu** card, tiga opsi
  (eskalasi / perpanjang 1 jam / abaikan); `timeout` tidak mengubah apa pun.

### Diubah

- `SupportAgent.escalate` menulis handoff `Support → Orchestrator (ticket_unresolved)`, bukan
  sekadar `UPDATE`; `triggers.run_trigger` langsung mengikuti rantainya, dan Orchestrator mencatat
  `escalation:<ticket>` untuk manusia.
- Scheduler: **8 job** hidup (tambah `handoff_check`), `PENDING_JOBS` tinggal 3 (semuanya W6).
- Selfcheck: **113 PASS / 0 FAIL** (12 cek W8 baru, termasuk rantai Sales → Marketing → Support
  dengan tiga node dan handoff yang habis diambil).

---

## Rev 3.5 — 17 Nov 2026 (W4 & W5 ditutup)

### Ditambahkan

- `hermes_agents/moderator.py`: `filter_comment`, `flag_content`, `ban_account` dengan tabel aturan
  (`piracy`, `abuse` → ban; `spam`, `spoiler` → flag). Setiap keputusan = satu baris
  `moderation_events` (append-only, DB-SCHEMA.md §14); status ban dihitung dari baris terakhir.
- `hermes_agents/ops.py` + job `ops_check` (tiap jam): enam pemeriksaan (disk, database, dlq,
  context, scheduler, mail), finding berlevel dengan saran tindakan, alert Discord opsional.
- `hermes_agents/inbox.py` + job `email_check` (tiap 5 menit): baca kotak masuk lewat IMAP stdlib,
  dekode subjek RFC 2047, buang kutipan balasan, lewati `Auto-Submitted` sendiri, dedupe UID di
  SharedContext, dan tiap surat jadi tiket lewat `run_trigger('new_email')` yang sama dengan webhook.

### Diubah

- Scheduler: **7 job** hidup (tambah `email_check`, `ops_check`), `PENDING_JOBS` tinggal 4
  (`weekly_report`, `cache_warmer`, `recommendation_batch`, `handoff_check`).
- `GET /health` → `pending_jobs` kini 4 entri; tidak ada job kosong yang didaftarkan.
- Selfcheck: **101 PASS / 0 FAIL** (13 cek baru untuk Moderator, Ops, dan kotak masuk dengan IMAP palsu).
- ENV-VARS.md §3c + `.env.example`: `IMAP_HOST`, `IMAP_PORT`, `IMAP_USER`, `IMAP_PASSWORD`,
  `IMAP_FOLDER`, `IMAP_MAX_PER_RUN`.

---

## Rev 3.4a — 17 Nov 2026 (rilis pertama)

Dokumen ini mencatat revisi; rilisnya diberi tag. Rilis pertama: **v0.5.0** (W1–W5 selesai) —
catatan rilis yang bisa dibaca orang luar ada di [RELEASES.md](RELEASES.md). Versi `0.x` = versi
lapisan Hermes (bridge, sidecar, agent); `package.json` 1.2.0 tetap versi aplikasi kantor.

---

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
