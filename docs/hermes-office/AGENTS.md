# Hermes Office — Katalog Agent

Nov 16, 2026 · @Shin · Sumber tunggal untuk config, tools, trigger, dan output agent.
Ruangan & id desk: [ROOMS.md](ROOMS.md). Handoff: [AGENT-HANDOFFS.md](AGENT-HANDOFFS.md).

**Total 46 agent** = 31 bisnis (5 generic + 26 AniWatch) + 15 specialist dev (12 base + 3 baru).

Bentuk dokumen ini dua lapis:

1. **Config** (§1) — yang ditulis ke kode. Nama, warna, emoji, ruangan, desk.
2. **Kartu agent** (§3) — yang dibaca manusia saat mengerjakan satu agent: trigger, tools, output,
   handoff, alur kerja, env yang dipakai.

Indeks cepat §2 hanya untuk mencari; detailnya selalu di kartu.

---

## 1. Config kanonik (`src/types.ts`)

Inilah satu-satunya definisi role bisnis. Semua string `role` di Python **harus** persis sama
dengan key di sini — typo berarti karakter tidak muncul tanpa error apa pun.

```ts
// ── Generic business roles ─────────────────────────────────────────────────
export const GENERIC_BIZ_CONFIGS = {
  Orchestrator: { color: '#8b5cf6', emoji: '🧠', desk: 'biz-b1', room: 'business-suite' },
  Sales:        { color: '#f59e0b', emoji: '💼', desk: 'biz-b2', room: 'business-suite' },
  Marketing:    { color: '#ec4899', emoji: '📣', desk: 'biz-b3', room: 'business-suite' },
  Ops:          { color: '#6366f1', emoji: '⚙️', desk: 'biz-b4', room: 'business-suite' },
  Support:      { color: '#10b981', emoji: '🎧', desk: 'biz-m1', room: 'main-office'    },
} as const

// ── AniWatch roles ─────────────────────────────────────────────────────────
export const ANIWATCH_AGENT_CONFIGS = {
  // Core Ops — server room, 24/7
  Scraper:          { color: '#64748b', emoji: '🕷️', desk: 'biz-s1', room: 'server-room' },
  Metadata:         { color: '#0ea5e9', emoji: '📋', desk: 'biz-s2', room: 'server-room' },
  Encoder:          { color: '#f97316', emoji: '🔄', desk: 'biz-s3', room: 'server-room' },
  Subtitle:         { color: '#38bdf8', emoji: '🌐', desk: 'biz-s4', room: 'server-room' },
  TranslationAgent: { color: '#34d399', emoji: '🌏', desk: 'biz-s5', room: 'server-room' },
  QualityChecker:   { color: '#84cc16', emoji: '🔍', desk: 'biz-s6', room: 'server-room' },
  EpisodeScheduler: { color: '#60a5fa', emoji: '📅', desk: 'biz-s7', room: 'server-room' },
  Notifier:         { color: '#facc15', emoji: '🔔', desk: 'biz-s8', room: 'server-room' },
  CacheWarmer:      { color: '#a78bfa', emoji: '⚡', desk: 'biz-s9', room: 'server-room' },
  Resolver:         { color: '#22d3ee', emoji: '🔗', desk: 'biz-s10', room: 'server-room' },

  // Community — main office
  Moderator:        { color: '#f43f5e', emoji: '🛡️', desk: 'biz-m2', room: 'main-office' },
  UserReportAgent:  { color: '#fb923c', emoji: '🚨', desk: 'biz-m3', room: 'main-office' },

  // Growth — creative studio
  Analytics:        { color: '#06b6d4', emoji: '📊', desk: 'biz-c1', room: 'creative-studio' },
  SEO:              { color: '#4ade80', emoji: '🔎', desk: 'biz-c2', room: 'creative-studio' },
  SocialMedia:      { color: '#fb7185', emoji: '📱', desk: 'biz-c3', room: 'creative-studio' },
  Recommendation:   { color: '#c084fc', emoji: '🎯', desk: 'biz-c4', room: 'creative-studio' },
  Retention:        { color: '#f472b6', emoji: '💌', desk: 'biz-c5', room: 'creative-studio' },

  // Premium pipeline — creative studio
  DesignAgent:      { color: '#e879f9', emoji: '🎨', desk: 'biz-c6', room: 'creative-studio' },
  QAAgent:          { color: '#a3e635', emoji: '✅', desk: 'biz-c7', room: 'creative-studio' },
  PricingAgent:     { color: '#fbbf24', emoji: '💰', desk: 'biz-c8', room: 'creative-studio' },
  PreviewAgent:     { color: '#7dd3fc', emoji: '👁️', desk: 'biz-c9', room: 'creative-studio' },
  Publisher:        { color: '#34d399', emoji: '🚀', desk: 'biz-c10', room: 'creative-studio' },

  // Finance / Legal / Security — finance & legal
  RevenueTracker:   { color: '#4ade80', emoji: '💵', desk: 'biz-f1', room: 'finance-legal' },
  PaymentAgent:     { color: '#34d399', emoji: '💳', desk: 'biz-f2', room: 'finance-legal' },
  DMCA:             { color: '#fca5a5', emoji: '⚖️', desk: 'biz-f3', room: 'finance-legal' },
  SecOps:           { color: '#94a3b8', emoji: '🔐', desk: 'biz-f4', room: 'finance-legal' },
} as const

export const BUSINESS_AGENT_CONFIGS = {
  ...GENERIC_BIZ_CONFIGS,
  ...ANIWATCH_AGENT_CONFIGS,
} as const

export type BusinessRole = keyof typeof BUSINESS_AGENT_CONFIGS
```

Catatan Rev 3.1 atas versi Rev 3: `desk` menunjuk spot yang benar-benar ada di `rooms.ts` (lihat
ROOMS.md), `room` memakai 4 ruangan baru, dan `QAAgent` memakai ✅ supaya tidak sama dengan
`QualityChecker` 🔍 di UI.

### Konflik nama yang harus dijaga

| Nama | Milik | Catatan |
| --- | --- | --- |
| `Security` | dev specialist (`security-auditor`) | **jangan** dipakai agent bisnis |
| `SecOps` | agent bisnis | semua `agent_start("SecOps Agent", "SecOps", …)` |
| `QualityChecker` | AniWatch (kualitas stream) | emoji 🔍 |
| `QAAgent` | premium (kualitas desain) | emoji ✅ |
| `Reviewer` | dev specialist (`code-reviewer`) | bukan agent bisnis |

Cara memanggil yang benar (nama tampilan bebas, **role key tidak**):

```python
bridge.agent_start("Scraper", "Scraper", task)                 # ✔
bridge.agent_start("Quality Checker", "QualityChecker", task)  # ✔ nama beda, key benar
bridge.agent_start("Scraper Agent", "scraper", task)           # ✘ key huruf kecil → tidak muncul
bridge.agent_start("Security Agent", "Security", task)         # ✘ bentrok specialist dev
```

---

## 2. Indeks cepat (30 agent bisnis)

| Role | Emoji | Rumah | Grup |
| --- | --- | --- | --- |
| Orchestrator | 🧠 | Business Suite | Koordinasi |
| Sales | 💼 | Business Suite | Generic |
| Marketing | 📣 | Business Suite | Generic |
| Ops | ⚙️ | Business Suite | Generic |
| Support | 🎧 | Main Office | Generic |
| Scraper | 🕷️ | Server Room | Core Ops |
| Metadata | 📋 | Server Room | Core Ops |
| Encoder | 🔄 | Server Room | Core Ops |
| Subtitle | 🌐 | Server Room | Core Ops |
| TranslationAgent | 🌏 | Server Room | Core Ops |
| QualityChecker | 🔍 | Server Room | Core Ops |
| EpisodeScheduler | 📅 | Server Room | Core Ops |
| Notifier | 🔔 | Server Room | Core Ops |
| CacheWarmer | ⚡ | Server Room | Core Ops |
| Moderator | 🛡️ | Main Office | Community |
| UserReportAgent | 🚨 | Main Office | Community |
| Analytics | 📊 | Creative Studio | Growth |
| SEO | 🔎 | Creative Studio | Growth |
| SocialMedia | 📱 | Creative Studio | Growth |
| Recommendation | 🎯 | Creative Studio | Product |
| Retention | 💌 | Creative Studio | Product |
| DesignAgent | 🎨 | Creative Studio | Premium |
| QAAgent | ✅ | Creative Studio | Premium |
| PricingAgent | 💰 | Creative Studio | Premium |
| PreviewAgent | 👁️ | Creative Studio | Premium |
| Publisher | 🚀 | Creative Studio | Premium |
| RevenueTracker | 💵 | Finance & Legal | Finance |
| PaymentAgent | 💳 | Finance & Legal | Finance |
| DMCA | ⚖️ | Finance & Legal | Legal |
| SecOps | 🔐 | Finance & Legal | Security |

---

## 3. Kontrak setiap agent

Semua agent bisnis adalah kelas dengan bentuk yang sama, supaya Orchestrator bisa memanggilnya
tanpa tahu isinya:

```python
class XAgent:
    def run_sync(self, data: dict) -> str:
        aid = bridge.agent_start("X Agent", "X", task_dari(data))
        try:
            bridge.agent_update(aid, "...")            # per langkah kerja
            result = self.do_work(data)                # tool calls
            bridge.agent_done(aid, result)
            return "done"
        except Exception as e:
            bridge.agent_error(aid, str(e), retrying=False)
            raise
```

Aturan:

1. **Satu agent = satu karakter.** Jangan spawn dua karakter untuk satu task.
2. `agent_update` minimal sekali per tool call; status text harus bisa dibaca manusia
   ("Menerjemahkan via deepl...", bukan "step 3").
3. Approval **selalu** lewat `bridge.agent_waiting(...)` lalu `bridge.wait_for_approval(...)`.
   Urutannya tidak boleh dibalik (fix Rev 3 #1 / Rev 3.1 #3).
4. Metric bisnis dikirim dari agent, bukan dihitung di UI.
5. Handoff memakai `SharedContext`, bukan import antar modul agent (AGENT-HANDOFFS.md).

---

## 4. Kartu agent

### 4.1 Koordinasi & Generic (5)

#### 🧠 Orchestrator — Koordinasi

**Key:** `Orchestrator` · **Rumah:** Business Suite · **Tools:** `delegate`, `monitor_agents`,
`reprioritize`, `escalate_to_human`
**Trigger:** semua webhook, semua job scheduler yang bersifat bisnis, chat manual
**Output:** routing ke agent yang tepat, satu baris "Delegasi ke X ✓"

```
1. run_orchestrator(trigger_type, data) dari FastAPI / scheduler
2. agent_start("Orchestrator", "Orchestrator", f"Route: {trigger_type}")
3. build_orchestrator_graph().invoke() → node sesuai route_trigger()
4. node agent berjalan (karakter kedua muncul di meja agent itu)
5. agent_done() setelah node selesai — Orchestrator tidak ikut bekerja
```

**Handoff:** → agent sesuai routing table; → manusia kalau 2× eskalasi gagal.
**Batas:** tidak boleh memanggil dirinya sendiri (re-entrant), tidak mengerjakan pekerjaan agent lain.
**Routing table:** [API-REFERENCE.md](API-REFERENCE.md) §4 (`SUPPORTED_TRIGGERS`) + AGENT-HANDOFFS.md.

#### 💼 Sales — Generic

**Key:** `Sales` · **Rumah:** Business Suite · **Tools:** `qualify_lead`, `draft_email`,
`send_email`, `update_crm`, `schedule_meeting`
**Trigger:** `new_lead`, `form_submit`, `deal_stage_change` (via Orchestrator); `@sales` di chat
**Output:** lead tersimpan + diskor, surat terkirim (SMTP), handoff ke Marketing/Support
**Handoff:** → Marketing (`lead_converted`: skor, nama, email) · → Support (`meeting_scheduled`:
waktu, kebutuhan khusus)
**Metric:** `leads_qualified`, `emails_sent`, `crm_updates`

**Implementasi W8 sisa:** `hermes_agents/sales.py`.

| Tool | Yang sebenarnya terjadi |
| --- | --- |
| `qualify_lead` | skor 0..1 dari payload saja (paket berbayar 0.30, anggaran ≥ Rp150rb 0.20 / ≥ Rp50rb 0.10, ≥10 karyawan 0.15, sumber referral/partner/community 0.15, domain non-mailbox 0.10, nama perusahaan 0.10). Tiap poin punya `{rule, points, detail}`; ambang `QUALIFY_MIN_SCORE = 0.5`. Tanpa LLM — skor yang tidak bisa dihitung ulang bukan metrik |
| `update_crm` | `lead:<id>` di SharedContext; hasilnya `backend: shared_context` + alasan. **`HUBSPOT_API_KEY` tidak dibaca** — tidak ada panggilan CRM yang bisa diklaim |
| `draft_email` / `send_email` | surat ucapan terima kasih lewat `mailer` (SMTP yang sama dengan Support). Tanpa `SMTP_HOST` → `sent: false` + alasan; lead tetap `qualified` |
| `schedule_meeting` | handoff `Sales → Support meeting_scheduled`; **tidak ada** penulisan kalender (`GOOGLE_*` belum diintegrasikan) dan hasilnya menyebut itu |

Trigger: `new_lead` & `form_submit` → skor, simpan, surat, handoff (kalau lolos ambang); kiriman
form kedua untuk lead yang sudah `qualified` = `duplicate` tanpa surat/handoff kedua. `deal_stage_change`
menerima `new`/`contacted`/`qualified`/`meeting`/`won`/`lost` plus alias (`closed_won` → `won`,
`demo` → `meeting`); `meeting` tanpa `when`+`timezone` **ditolak utuh** (bukan setengah jalan), dan
lead yang tidak ada di SharedContext ditolak dengan alasan. `/leads` membaca hasilnya.

#### 📣 Marketing — Generic

**Key:** `Marketing` · **Rumah:** Business Suite · **Tools:** `draft_post`, `schedule_post`,
`fetch_analytics`, `generate_report`
**Trigger:** `weekly_analytics` (Senin 09.00, job `weekly_report`); `analytics_ready` tetap milik
Analytics, `content_schedule` milik SocialMedia
**Output:** weekly report (file markdown + ringkasan Discord)
**Handoff:** → Support (`customer_onboarding`: plan, channel akuisisi)

**Implementasi W6:** `hermes_agents/marketing.py`, `MarketingAgent.weekly_report()` dipanggil lewat
`run_trigger('weekly_analytics')` (bukan import agent), menulis
`media/published/reports/weekly-<ISO week>.md` dari `growth_data.snapshot()` dan mengirim satu baris
ringkasan ke Discord kalau `DISCORD_WEBHOOK_URL` diisi. Setiap bagian laporan menyebut sumber
angkanya (`local` atau `feed+local`); bagian tontonan menyatakan belum ada kalau `ANALYTICS_FEED`
kosong. `draft_post`/`schedule_post` yang berdiri sendiri belum dipakai — belum ada penjadwal
konten di luar episode.

**Implementasi W8 sisa:** `MarketingAgent.onboard_lead()` adalah node yang menerima handoff
`Sales → Marketing lead_converted`: satu surat selamat datang lewat `mailer`, satu catatan
`campaign:<lead>` di SharedContext, lalu handoff `Marketing → Support customer_onboarding`
(plan + channel). Satu lead hanya sekali dicoba dikirimi — konversi kedua (deal yang baru menutup
setelah form-nya sudah qualified) menjawab `duplicate` dan tidak membuka tiket onboarding kedua.
Tanpa `SMTP_HOST` suratnya `sent: false` dengan alasan yang tersimpan di `campaign:<lead>`; Support
tetap menerima handoff-nya, karena follow-up manual justru yang dibutuhkan saat surat gagal.
Surat yang gagal tidak hilang: job `campaign_retry` (tiap 15 menit) mengirim ulang dari catatan yang
sama dengan jeda 15 → 30 → 60 menit, maksimal empat percobaan. Retry hanya menulis ulang
`campaign:<lead>` — tidak ada handoff kedua, jadi tiket onboarding tetap satu per lead; sesudah
empat percobaan catatan berhenti di `sent: false` beserta error terakhir untuk dilihat manusia.

Catatan yang berhenti itu tidak hanya ada bagi yang membuka SharedContext:
`marketing.gave_up_campaigns()` membacanya, dan `/biz` serta `/leads` menyebut lead-nya di satu baris
(`campaigns_gave_up` di respons). Baris itu berasal dari DB sidecar sendiri, jadi `/biz` tetap
melaporkannya saat kantor mati.

#### ⚙️ Ops — Generic

**Key:** `Ops` · **Rumah:** Business Suite · **Tools:** `check_system`, `run_workflow`,
`generate_report`, `send_alert`
**Trigger:** `chargeback_received` (via Orchestrator); system check tiap jam (langsung, bukan lewat
Orchestrator karena tidak menghasilkan karakter)
**Output:** alert anomali, laporan sistem
**Handoff:** → SecOps saat anomali berpola serangan; → manusia saat butuh keputusan infra

**Implementasi W5:** `hermes_agents/ops.py`, dijalankan job `ops_check` tiap jam. Enam pemeriksaan:
`disk` (sisa < 10% = critical), `database` (`PRAGMA quick_check` + ukuran), `dlq` (isi antrean),
`context` (baris SharedContext menua), `scheduler` (job terdaftar & punya `next_run_time`), `mail`
(SMTP siap / kiriman gagal 24 jam terakhir). Hasilnya finding berlevel + saran tindakan; alert hanya
dikirim kalau `DISCORD_WEBHOOK_URL` diisi, dan kegagalan alert tidak menggagalkan job. Tidak ada
auto-fix di sini — yang membereskan tetap job `jobs.py`.

#### 🎧 Support — Generic

**Key:** `Support` · **Rumah:** Main Office · **Tools:** `triage_ticket`, `search_kb`,
`draft_reply`, `send_reply`, `escalate`, `sla_stats`
**Trigger:** `support_ticket`, `new_email`, SLA breach, `forward_to_support` dari UserReportAgent
**Output:** tiket resolved atau dieskalasi
**Handoff:** → Orchestrator (`ticket_unresolved`: alasan + 3 pesan terakhir)
**Slash:** `/tickets`, `/sla`

Alur dengan knowledge base:

```
tiket masuk → triage (kategori + prioritas) → kb.search(subject, top_k=3)
   ├── skor ≥ KB_MIN_SCORE  → draft_reply dari artikel → send_reply
   └── skor <  KB_MIN_SCORE → escalate (ke Orchestrator, lalu manusia)
```

- `KB_MIN_SCORE` (default `0.5`) **relatif** (FTS5 bm25), bukan probabilitas. Kalibrasi ulang
  setelah ≥ 20 artikel; jangan percaya angka default untuk produksi.
- SLA: `received_at + 3600` (1 jam). `check_sla_breaches` menagih tiket lewat deadline dengan
  permission card 3 pilihan: *Handle sekarang* / *Extend SLA +30 menit* / *Close as resolved*.
- ⚠️ `wait_for_approval` hanya dipanggil **setelah** card dikirim, dan hanya **sekali** per tiket
  (fix Rev 3 #1 — versi lama memanggilnya dua kali dan agent menggantung).
- Tiket disimpan di tabel `tickets` (DB-SCHEMA.md), context-nya key `ticket:<id>`.
- `send_reply` **benar-benar mengirim** lewat SMTP (`hermes_agents/mailer.py`, ENV-VARS.md §3b).
  Hasilnya menentukan status: terkirim → `pending` + counter `emails_sent`; gagal → tiket tetap `open`,
  alasan disimpan di context (`send_error`) dan di outbox, supaya kartu SLA berikutnya menagihnya.
- `first_response_at` (W10) hanya diisi balasan terkirim pertama (`COALESCE`), dan `sla_stats()`
  menghitung compliance tiket selesai + rata-rata respons dari kolom itu. Gauge
  `sla_avg_response_min` yang `0` dengan sampel `0` berarti belum ada data; `/sla` menyebut jumlah
  sampelnya supaya angka nol tidak terbaca sebagai respons instan.

---

### 4.2 Core Ops — Server Room (10)

Pipeline episode bersifat sequential dan dijaga Orchestrator:

```
Scraper → Metadata → Encoder → Subtitle → TranslationAgent → QualityChecker
        → EpisodeScheduler ──(embargo habis)──▶ live
        → Notifier (feed) → SocialMedia (Discord/Telegram) → SEO (meta + sitemap)
```

#### 🕷️ Scraper

**Key:** `Scraper` · **Tools:** `fetch_source`, `save_episode`, `check_duplicate`
**Trigger:** tiap N menit, episode baru rilis, retry dari QualityChecker
**Output:** episode tersimpan di DB (belum live)
**Handoff:** → Metadata (`episode_fetched`: episode_id, source)
**Catatan:** `check_duplicate` wajib sebelum `save_episode` — episode ganda merusak antrian embargo.
**Implementasi W11d:** `hermes_agents/scraper.py` memicu backend lewat `POST /v1/admin/scrape/backfill`
(`backfill`), `POST /v1/admin/scrape/run` (`run_target`, `dry_run` untuk uji parser) dan membaca
`GET /v1/admin/sources/health` + `GET /v1/admin/scrape/queue`. Role ini **tidak** mengikis situs dari
laptop. `propose_domain()` hanya mengirim kartu approval berisi bukti; ia tidak pernah memanggil
PATCH `baseurl` (W11-SCRAPER-RESOLVER.md §8).

#### 🔗 Resolver

**Key:** `Resolver` · **Tools:** `resolve_page`, `probe_media`, `report_host`
**Trigger:** job `resolver_refresh` tiap 6 jam, `/resolver`, dan `need_direct` yang menua
**Output:** `direct_ready` (provider, `probe {status, content_type, bytes}`, `expires_at`) — URL putar
**tidak** disimpan (D-64)
**Handoff:** ← Scraper (`need_direct`) · → Scraper (`direct_ready`)
**Implementasi W11d:** `hermes_agents/resolver.py` membaca `need_direct` dari SharedContext lalu
memanggil `POST /v1/admin/media/resolve` (dry run, tidak menulis DB di kedua sisi). Host yang tidak
punya adapter dilaporkan sebagai `host_not_supported` dan dihitung di `unresolved`, bukan disembunyikan.
**Batas:** `PageResolver` dan `LinkResolver` hidup di backend Go (`internal/pageresolve`, `internal/media`);
role ini bukan lapis ketiga, bukan host `direct`, dan tidak mengganti domain situs

#### 📋 Metadata

**Key:** `Metadata` · **Tools:** `fetch_mal`, `fetch_anilist`, `update_db`
**Trigger:** setelah Scraper · **Output:** judul, synopsis, thumbnail, genre, rating
**Handoff:** → Encoder
**Implementasi W3:** `hermes_agents/media.py` (`derive_metadata()`) memakai sidecar `<episode>.json`; kalau tidak
ada, judul diturunkan dari slug nama file. `fetch_mal`/`fetch_anilist` **belum** dipanggil (butuh
key), dan itu bukan fallback diam-diam: `metadata_source` mencatat `sidecar` atau `filename`.

#### 🔄 Encoder

**Key:** `Encoder` · **Tools:** `encode_video`, `generate_thumbnail`, `upload_cdn`
**Trigger:** file baru dari Metadata · **Output:** 360p/720p/1080p + thumbnail di CDN
**Handoff:** → Subtitle
**Env:** `CDN_API_KEY`, `CDN_BASE_URL`
**Implementasi W3:** 720p H.264/AAC lewat `ffmpeg` (default). Tanpa ffmpeg pakai
`HERMES_ENCODER=copy`; hasilnya mencatat `encode_mode: copy`, jadi tidak ada episode yang mengaku
di-transcode padahal hanya disalin. Upload CDN belum dipanggil (opsional, `CDN_BASE_URL` hanya
dipakai Notifier untuk URL feed).

#### 🌐 Subtitle

**Key:** `Subtitle` · **Tools:** `fetch_subtitle`, `sync_timing`, `detect_encoding`
**Trigger:** setelah Encoder · **Output:** subtitle tersinkron, encoding diperbaiki
**Handoff:** → TranslationAgent
**Batas:** hanya timing & encoding. Terjemahan bukan tugasnya.
**Implementasi W3:** `.srt` dan `.ass` dibaca (`parse_subtitle`), isinya dinormalisasi ke UTF-8 dan
ditulis sebagai `<episode>.id.srt`; baris `subtitle_tracks` dibuat dengan `status='ready'`.

**Status:** selesai di W3 bersama pipeline — ticket W5 tinggal Moderator, OpsAgent, dan `email_check`.

#### 🌏 TranslationAgent

**Key:** `TranslationAgent` · **Tools:** `fetch_raw_subtitle`, `translate_text`, `qa_translation`,
`save_translated_sub`, `request_human_review`
**Trigger:** setelah Subtitle · **Output:** sub terjemahan siap attach, atau eskalasi QA
**Handoff:** → QualityChecker (selesai) · → manusia (QA di bawah threshold)
**Slash:** `/translations`, `/approve-sub [episode_id]`

```
1. fetch_raw_subtitle(episode_id)                     .srt/.ass dari Subtitle
2. translate_text(raw, provider=TRANSLATION_PROVIDER) deepl | openai | local (Hermes)
3. qa_translation(original, translated) → skor 0..1
4. skor < TRANSLATION_QA_THRESHOLD (0.75):
     agent_waiting → options ["Approve & Lanjutkan", "Reject & Translate Ulang"]
     wait_for_approval(timeout=3600); selain "Approve" → agent_error, return "rejected"
5. save_translated_sub() → subtitle_tracks status ready
6. agent_done() → QualityChecker
```

**Env:** `TRANSLATION_PROVIDER`, `DEEPL_API_KEY`, `TRANSLATION_QA_THRESHOLD`
**Implementasi W3:** `local` = glossary (`HERMES_GLOSSARY`), dan skor QA =
proporsi baris yang benar-benar berubah. Baris yang tidak ada di glossary dibiarkan apa adanya, jadi
skor 0 berarti "tidak diterjemahkan", bukan "mirip". `deepl`/`openai` tanpa key gagal jelas
(`MissingCredentials`).

#### 🔍 QualityChecker

**Key:** `QualityChecker` · **Tools:** `check_stream`, `check_subtitle_sync`, `verify_404`
**Trigger:** setelah TranslationAgent; re-check dari UserReportAgent
**Output:** report kualitas (lolos / corrupt) — semua subtitle track diperiksa
**Handoff:** → EpisodeScheduler (lolos) · → Orchestrator (`qc_failed`: jenis kerusakan, attempt)
**Aturan:** dua kali gagal pada episode yang sama → pipeline dibatalkan, eskalasi ke manusia.

#### 📅 EpisodeScheduler

**Key:** `EpisodeScheduler` · **Tools:** `queue_episode`, `check_embargo`, `trigger_publish`,
`cancel_schedule`
**Trigger:** setelah QC lolos; satu putaran tiap menit dari scheduler
**Output:** episode live tepat waktu, embargo terjaga
**Handoff:** → Orchestrator (`episode_released`) → Notifier + SocialMedia
**Slash:** `/schedule`, `/embargo [episode_id]`, `/cancel-schedule [episode_id]`

```
1. QC memanggil schedule_episode(..., embargo_until)  → status "scheduled"
2. tiap menit: SELECT ... WHERE embargo_until <= now AND status='scheduled'
3. publish atomik: UPDATE ... SET status='live' WHERE episode_id=? AND status='scheduled'
   changes == 0 → sudah dibatalkan DMCA, jangan publish
4. run_orchestrator("episode_released", {...}) → Notifier + SocialMedia
5. DMCA sebelum embargo: cancel_schedule() → "cancelled", tidak pernah live
   DMCA setelah live: unpublish + purge_cdn
```

**Schema:** `episode_schedule` (DB-SCHEMA.md §5). `embargo_until` dalam **detik** epoch
(`time.time()`), bukan milidetik.

#### 🔔 Notifier

**Key:** `Notifier` · **Tools:** `push_notif`, `update_rss`, `update_feed`
**Trigger:** episode live · **Output:** subscriber dinotif, RSS/feed terupdate
**Handoff:** → SocialMedia (`announce_episode`)
**Implementasi W3/W6:** selalu menulis `media/published/notifications.jsonl` + `feed.xml` (RSS 2.0).
Sejak W6 **posting platform adalah tugas SocialMedia** (`social.py`): Notifier hanya menulis feed dan
log, dan `pipeline.announce` menjalankan tiga karakter berurutan — Notifier (feed), SocialMedia
(satu post per channel), SEO (meta + sitemap). Pemisahan ini yang membuat satu episode tidak
diumumkan dua kali di Discord yang sama. `notified_channels` dan `notified_skipped` diisi dari
hasil SocialMedia, termasuk alasannya saat channel kosong.

#### ⚡ CacheWarmer

**Key:** `CacheWarmer` · **Tools:** `get_trending`, `warm_cdn_cache`
**Trigger:** harian 17.00 (langsung dari scheduler) · **Output:** CDN hangat sebelum prime time
**Batas:** tidak mem-publish apa pun; hanya cache.

**Implementasi W6:** `hermes_agents/cache_warmer.py`. `get_trending` = episode `live` terbaru dari
`episode_schedule` — fork ini tidak punya angka tontonan untuk merangking, jadi "trending" berarti
"paling baru", bukan tebakan. `warm_cdn_cache` melakukan `GET` sungguhan per file ke `CDN_BASE_URL`;
tanpa variabel itu hasilnya `warmed: 0` + alasan, bukan "cache hangat" palsu.

---

### 4.3 Community — Main Office (2 + Support)

#### 🛡️ Moderator

**Key:** `Moderator` · **Tools:** `filter_comment`, `flag_content`, `ban_account`
**Trigger:** komentar/report masuk · **Output:** komentar bersih, akun di-ban
**Slash:** `/unban [ip/user]`
**Aturan:** `ban_account` harus menyimpan alasan + `rule` yang dilanggar (audit, SECURITY.md §10).

**Implementasi W5:** `hermes_agents/moderator.py`. Empat aturan kecil dan deterministik (`piracy`,
`abuse` → ban; `spam`, `spoiler` → flag), karena ban harus bisa dijelaskan ke orang yang kena.
Setiap keputusan menulis satu baris `moderation_events` (append-only, §14 DB-SCHEMA). Komentar tanpa
`user_id` ditandai, bukan menggagalkan job. Belum ada trigger komentar di 13 trigger bisnis; agent
ini dipanggil dari antrean moderasi yang menyusul, dan hari ini diuji di selfcheck.

#### 🚨 UserReportAgent

**Key:** `UserReportAgent` · **Tools:** `triage_report`, `check_episode_health`,
`trigger_qc_pipeline`, `forward_to_support`, `notify_user`, `log_report`
**Trigger:** `user_report` (tombol "Laporkan Masalah") · **Output:** report terklasifikasi, QC
di-trigger, user dinotif
**Handoff:** → QualityChecker (teknis) · → Support (akun/billing)
**Slash:** `/reports`, `/report-stats`

```
laporan → triage_report
  ├── technical (video/subtitle/404) → check_episode_health
  │      ├── bermasalah → trigger_qc_pipeline → notify_user("sedang diperbaiki")
  │      └── normal     → notify_user("coba clear cache")
  ├── account/billing → forward_to_support → Support 🎧
  └── spam/duplikat   → log_report → selesai
```

**Schema:** `user_reports` (DB-SCHEMA.md §4).

---

### 4.4 Growth & Product — Creative Studio (5)

#### 📊 Analytics

**Key:** `Analytics` · **Tools:** `fetch_watch_data`, `detect_dropoff`, `generate_report`
**Trigger:** `analytics_ready` · **Output:** snapshot mingguan + daftar drop-off

**Implementasi W6:** `hermes_agents/analytics.py`, dengan `growth_data.py` sebagai sumber angka.
Dua sumber, dan hasilnya selalu menyebut yang dipakai: export AniWatch (`ANALYTICS_FEED`) dan DB fork
ini sendiri (`episode_schedule`, `tickets`, `user_reports`). Tanpa export, `source: "local"` dan
`insufficient` menyebut bahwa tontonan/watch time/drop-off belum bisa dihitung — tidak ada angka
karangan. Drop-off hanya dilaporkan kalau `views ≥ 20` dan penyelesaian < 50%; baris tanpa `views`
dilewati, karena metrik yang tidak ada bukan nol. Snapshot ditulis ke
`media/published/analytics/YYYY-MM-DD.json`.

#### 🔎 SEO

**Key:** `SEO` · **Tools:** `update_meta`, `update_sitemap`, `add_structured_data`
**Trigger:** akhir pipeline episode (episode baru live) · **Output:** meta per episode, `sitemap.xml`,
`structured-data.json`

**Implementasi W6:** `hermes_agents/seo.py`. Semuanya membaca `episode_schedule` dengan `status='live'`
— episode `cancelled` **tidak** masuk sitemap — dan ditulis ke folder yang sama dengan `feed.xml`:
`media/published/meta/<episode_id>.json`, `sitemap.xml`, `structured-data.json` (JSON-LD
`TVEpisode`). Fork ini tidak meng-upload apa pun: `base_url` di hasil adalah `SEO_SITE_URL`, atau
`CDN_BASE_URL`, atau `relative` — dan situs yang mengambil file itu.

#### 📱 SocialMedia

**Key:** `SocialMedia` · **Tools:** `post_discord`, `post_telegram`, `post_twitter`,
`announce_episode`
**Trigger:** akhir pipeline episode; `announce_episode` dan `content_schedule` dari webhook
**Output:** satu pengumuman per platform per episode

**Implementasi W6:** `hermes_agents/social.py` + `channels.py`. Setiap platform mengembalikan
`{posted, reason}`; variabel yang kosong jadi `skipped` yang menyebut namanya. Satu episode = satu
post per channel: yang sudah terkirim dicatat di SharedContext (`social:<episode_id>`), jadi trigger
`announce_episode` yang datang setelah publish tidak mengulang post, sementara kiriman yang gagal
tidak dicatat sehingga percobaan berikutnya masih boleh. X/Twitter **belum diimplementasikan**
(posting butuh OAuth 2.0 user context; bearer token hanya untuk baca) dan itu tertulis di hasilnya,
bukan didiamkan. Instagram belum punya jalur API di fork ini.

#### 🎯 Recommendation

**Key:** `Recommendation` · **Tools:** `fetch_history`, `run_model`, `save_recs`
**Trigger:** batch Minggu 22.00 (langsung dari scheduler) · **Output:** rekomendasi personal per user

**Implementasi W6:** `hermes_agents/recommendation.py`. Modelnya co-view yang bisa dijelaskan: user
yang menonton episode sama dianggap pasangan, skor = berapa co-viewer menonton episode itu, dan
episode yang sudah ditonton tidak pernah direkomendasikan. Hasil ditulis ke `RECOMMENDATION_DB`
(tabel `recommendations`, dibuat kalau belum ada) atau, kalau variabel itu kosong, ke
`media/published/recommendations.jsonl`. Hasilnya menyebut `target` sehingga tidak ada klaim "sudah
tersimpan di DB AniWatch" tanpa bukti.

#### 💌 Retention

**Key:** `Retention` · **Tools:** `segment_users`, `draft_email`, `send_campaign`
**Trigger:** `retention_check` · **Output:** campaign re-engagement terkirim (SMTP) atau dilewati
dengan alasan

**Implementasi W6:** `hermes_agents/retention.py`. Segmen = baris `subscription_status` yang sudah
kedaluwarsa atau sedang masa tenggang (ditulis PaymentAgent, W9 — sebelum itu segmennya kosong dan
agent mengatakannya). Surat hanya dikirim ke user yang **id-nya memang alamat email**: tabel itu
tidak punya kolom `email`, dan menebak alamat orang lain lebih buruk daripada melewatinya. Campaign
terkirim dicatat (`retention:<user_id>`) dan tidak diulang dalam 7 hari; yang gagal tidak dicatat,
jadi dicoba lagi putaran berikutnya. Pengiriman lewat `hermes_agents/mailer.py` yang sama dengan
Support.

---

### 4.5 Premium pipeline — Creative Studio (5)

```
DesignAgent 🎨 3–5 variasi → QAAgent ✅ filter → PricingAgent 💰 tier
  → PreviewAgent 👁️ mockup light+dark → ✋ approval (Approve/Revisi/Reject)
        ├── Approve → Publisher 🚀 live
        ├── Revisi  → DesignAgent 🎨 ulang
        └── Reject  → selesai
```

| Agent | Key | Tools | Output |
| --- | --- | --- | --- |
| 🎨 DesignAgent | `DesignAgent` | `generate_design`, `save_draft` | 3–5 variasi (border/nameplate/effect) |
| ✅ QAAgent | `QAAgent` | `check_resolution`, `check_consistency`, `check_transparency` | desain yang lolos filter |
| 💰 PricingAgent | `PricingAgent` | `analyze_complexity`, `assign_tier` | tier harga |
| 👁️ PreviewAgent | `PreviewAgent` | `render_mockup`, `bundle_preview` | mockup light + dark |
| 🚀 Publisher | `Publisher` | `upload_cdn`, `insert_db`, `activate_item` | item `live` di DB + manifest |

Detail per agent:

- **DesignAgent** — `/design [kind] [tema]` (kind: `border`, `nameplate`, `profile_effect`; tema:
  `neon`, `sakura`, `ocean`). **Implementasi W7:** `hermes_agents/premium.py` membuat **tiga variasi
  SVG deterministik** dari palet tema, `design_source: "template"`. Provider image-gen **tidak**
  dipanggil: `IMAGE_GEN_API_KEY` yang diisi hanya dicatat sebagai `image_gen: "belum
  diimplementasikan"`, bukan diklaim sudah dipakai.
- **QAAgent** — tiga cek atas berkas yang ditulis: resolusi kanvas, warna di luar palet (tema tak
  dikenal = gagal), dan latar penuh yang menutupi transparansi. Lolos → diteruskan; gagal → Design
  mengulang sekali, lalu item `rejected` dengan `qa_problems` di context.
- **PricingAgent** — tabel `TIERS` atas jumlah elemen (`basic` 15.000, `premium` 35.000, `deluxe`
  75.000), bukan perkiraan LLM.
- **PreviewAgent** — `preview-light.svg` + `preview-dark.svg` di `media/premium/<id>/`; kartu
  approval (Approve/Revisi/Reject) diangkat dari sini, timeout **24 jam** (keputusan uang tidak
  mewarisi 300 dtk). `/pending-items` menampilkan yang `pending_approval`.
- **Publisher** — hanya dari status `approved`, idempoten (keputusan kedua tidak menulis manifest
  kedua). Menulis `media/published/premium/<id>.json` dan status `live`; **tidak** meng-upload apa
  pun, dan manifest menyatakan `cdn.uploaded: false` beserta alasannya. Handoff → RevenueTracker
  saat item terjual belum ada (RevenueTracker W9).

**Satu penulis status:** `premium.decide()` dipakai tombol kartu (lewat `request_approval` →
`char.ask`) **dan** `/approve`, jadi kedua pintu berakhir di status yang sama. `timeout` tidak
mengubah apa pun — item tetap `pending_approval` supaya `/approve` masih bisa mengambilnya.

---

### 4.6 Finance, Legal, Security — Finance & Legal (4)

#### 💵 RevenueTracker

**Key:** `RevenueTracker` · **Tools:** `record_transaction`, `generate_snapshot`, `detect_anomaly`
**Trigger:** payment sukses (dipanggil PaymentAgent), harian
**Output:** laporan revenue harian/mingguan, alert anomali
**Slash:** `/revenue`, `/topselling`

**Implementasi W9:** `hermes_agents/finance.py`. `record_transaction()` adalah node graph-nya:
handoff `payment_settled` masuk, lalu snapshot ditulis ke
`media/published/revenue/YYYY-MM-DD.json`. Angkanya dari `payment_events` saja, **satu baris per
`order_id`** (status baris terbaru), jadi order yang di-chargeback tidak dihitung dua kali. Dua
aturan anomali, keduanya bisa diperiksa: `refund_rate > 20%` (hanya kalau ≥ 5 order berbayar dalam 7
hari — persentase dari tiga order adalah derau, jadi nilainya `None`) dan `chargebacks ≥ 2` dalam 7
hari. `/topselling` masih rencana W10 karena penjualan per item belum punya sumber data.

#### 💳 PaymentAgent

**Key:** `PaymentAgent` · **Tools:** `handle_success`, `handle_failure`, `retry_subscription`,
`process_refund`, `flag_chargeback`
**Trigger:** Midtrans → `/webhook/payment` (setelah signature terverifikasi)
**Output:** kegagalan bayar tertangani, grace period diset, refund diproses, chargeback dieskalasi
**Handoff:** → RevenueTracker (sukses) · → SecOps (chargeback) · → manusia (approval refund)
**Slash:** `/payments`, `/subscriptions`, `/refunds`, `/chargeback`

| Event Midtrans | Aksi |
| --- | --- |
| `payment.success` | status order sukses → RevenueTracker; metric `emails_sent` tidak, `refunds_processed` tidak |
| `payment.failed` | status gagal, notif user + saran metode alternatif |
| `subscription.renewal_failed` | retry < 2 → grace 3 hari + notif; retry ≥ 2 → downgrade `free` + metric `subscriptions_lost` |
| `refund.requested` | window 7 hari; valid → approval card (Approve/Tolak/Minta Info), timeout **24 jam** |
| `chargeback.received` | revoke item, status `chargeback`, trigger `chargeback_received` → Ops + SecOps, metric `chargebacks` |

**Schema:** `payment_events`, `subscription_status` (DB-SCHEMA.md §7). Idempoten: `INSERT OR IGNORE`
atas `payment_events.id` — notifikasi ganda tidak boleh menghasilkan refund ganda.

**Implementasi W9:** `hermes_agents/finance.py`.

| Event | Fungsi | Hasil yang bisa diperiksa |
| --- | --- | --- |
| `settlement`/`capture` | `handle_success()` | baris `subscription_status` (plan, `retry_count=0`, `grace_until NULL`) + handoff `payment_settled` |
| `deny`/`cancel`/`expire`/`failure` | `handle_failure()` | `retry_count+1`; < 2 → `grace_until = now + 3 hari` + surat saran metode lain; ≥ 2 → plan `free`, `subscriptions_lost` |
| `refund_request` | `refund_request()` → `request_refund_approval()` | baris `pending` di `payment_events`; kartu Approve/Tolak/Minta Info (24 jam); Approve → `refunded` + `refunds_processed`, Tolak → `failed`, timeout tidak mengubah apa pun |
| `chargeback` | `flag_chargeback()` | baris `chargeback`, item `item_id` → `revoked`, `chargebacks`, handoff → SecOps |
| `refund` dari provider | `refund_completed()` | permintaan kita ditutup; **tidak** menambah `refunds_processed` karena keputusan itu bukan milik kita |

`refund_request` bukan status Midtrans: itu cara refund **diminta** lewat pintu yang sama
(`POST /webhook/payment`), sehingga jalur permintaan ikut terverifikasi signature. `subscription_status`
hanya ditulis dua fungsi di tabel ini — itulah yang membuat segmen `retention.py` punya sumber nyata.
Pencabutan item jujur soal batasnya: `premium_items` tidak menyimpan pemilik, jadi hanya `item_id`
yang disebut di notifikasi yang bisa dicabut.

#### ⚖️ DMCA

**Key:** `DMCA` · **Tools:** `verify_request`, `unpublish_episode`, `purge_cdn`
**Trigger:** takedown request masuk · **Output:** episode unpublish + CDN purge, atau
`cancel_schedule` kalau belum live
**Handoff:** → EpisodeScheduler (`takedown`: episode_id/anime_id, rentang)
**Aturan:** bukti permintaan tidak pernah dihapus, hanya status yang berubah.

**Implementasi W9:** `hermes_agents/dmca.py`. Pintunya `/takedown [episode_id] [alasan]` di chat —
fork ini **tidak** menambah trigger webhook ke-14; nota takedown datang lewat email/pos dan seseorang
menjalankan command itu. Urutannya: verifikasi (`episode_id`, `requester`, `reason`) → catat di
`dmca_requests` (termasuk yang ditolak) → handoff `DMCA → EpisodeScheduler` → node EpisodeScheduler
memanggil `cancel_schedule` (belum live, atomik `WHERE status='scheduled'`) atau unpublish (sudah
live, baris tetap ada). Keterbatasan yang ditulis, bukan disembunyikan: takedown per anime
(`anime_id` saja) ditolak karena fork ini menjadwalkan per `episode_id`, dan `cdn_purged` selalu
`false` dengan alasannya.

#### 🔐 SecOps

**Key:** `SecOps` · **Tools:** `monitor_events`, `apply_rule`, `escalate`
**Trigger:** loop monitor 10 detik; dipanggil Ops saat chargeback
**Output:** ancaman terdeteksi + diblokir (ban IP, soft lock, rate limit, flag account)
**Handoff:** → manusia lewat permission card untuk eskalasi
**Slash:** `/security`, `/incidents`

| Rule | Threshold | Window | Aksi |
| --- | --- | --- | --- |
| `login_attempts` | 5 | 60 dtk | `ban_ip` |
| `concurrent_devices` | 3 | 300 dtk | `soft_lock` |
| `request_rate` | 120 | 60 dtk | `rate_limit` |
| `chargeback_count` | 2 | — | `flag_account` |

**Aturan event:** `agent_working` hanya dikirim saat **ada** pelanggaran. Loop 10 detik yang
mengirim event tiap putaran akan membanjiri kantor (PLAN.md §Risiko).

**Implementasi W9:** `hermes_agents/sec_ops.py`. `monitor()` menjalankan empat rule di atas dan
menulis satu baris `security_incidents` per aksi (append-only; `/unban` menambah baris `unban`, bukan
menghapus). Sumber event menentukan kejujurannya: `login_attempts`, `concurrent_devices` dan
`request_rate` membaca `SECURITY_EVENT_FEED` (JSONL akses) — fork ini tidak punya access log sendiri,
jadi tanpa file itu `insufficient` menyebutnya dan `violations` kosong, bukan "traffic bersih".
`chargeback_count` dibaca dari `payment_events`, jadi rule itu bekerja di instalasi kosong.
`char.update` hanya dipanggil kalau ada pelanggaran baru, dan rule+target yang sama dalam 300 dtk
adalah satu insiden, bukan aliran event.

---

## 5. Tim dev — 15 specialist

12 dari base + 3 baru untuk AniWatch. Ini **bukan** agent bisnis: mereka dipanggil dari chat
routing dan bekerja lewat Claude Code, jadi tidak punya config `BUSINESS_AGENT_CONFIGS`.

| # | Key (`AGENT_CONFIGS`) | Tampilan | Fokus |
| --- | --- | --- | --- |
| 1 | `debugger` | Debugger | bug hunt, stack trace |
| 2 | `code-reviewer` | Reviewer | review diff |
| 3 | `frontend-developer` | Frontend | UI/React |
| 4 | `test-engineer` | Tester | test & coverage |
| 5 | `security-auditor` | Security | audit (bukan `SecOps`) |
| 6 | `devops-engineer` | DevOps | CI, deploy |
| 7 | `performance-engineer` | PerfEng | profiling |
| 8 | `database-architect` | DBA | schema & query |
| 9 | `typescript-pro` | TS Pro | tipe & build |
| 10 | `ai-engineer` | AI Eng | prompt & model |
| 11 | `fullstack-developer` | Fullstack | end-to-end |
| 12 | `architect-reviewer` | Architect | desain sistem |
| 13 | `player-dev` **(baru)** | Player Dev | HLS, buffering, adaptive, subtitle render |
| 14 | `stream-dev` **(baru)** | Stream Dev | CDN, encoding, latency, ffmpeg |
| 15 | `mobile-dev` **(baru)** | Mobile Dev | iOS/Android, push notif, offline |

Routing di base terjadi lewat **mention** di chat (`@Debugger lihat ini`), bukan kata kunci otomatis
(`server/index.js` hanya menghitung mention kalau agent itu ada di kantor). Jadi tiga specialist baru
butuh dua hal: entri di `AGENT_CONFIGS` (`src/types.ts`) dan bisa dipanggil dengan namanya.

Kalau nanti mau routing otomatis berbasis kata kunci, itu fitur baru di `server/index.js` — belum
ada di base, dan bukan bagian W2. Usulan katanya:

```js
// USULAN, belum ada di base — jangan ditulis ke kode sebelum fiturnya dibangun
const ANIWATCH_KEYWORDS = {
  'player, hls, buffering, adaptive, m3u8': 'Player Dev',
  'cdn, encoding, latency, bandwidth, ffmpeg': 'Stream Dev',
  'ios, android, mobile app, react native, flutter': 'Mobile Dev',
}
```

---

## 6. Menambah agent baru

1. Tentukan **ruangan + desk** kosong di [ROOMS.md](ROOMS.md) (kalau tidak ada, tambah spot dulu).
2. Tambah entri di `BUSINESS_AGENT_CONFIGS` — key = role string, warna unik, emoji belum dipakai.
3. Buat `hermes_bridge/agents/<nama>.py` dengan kontrak §3.
4. Daftarkan tools-nya di deskripsi agent (string tool **harus** sama dengan yang dipanggil).
5. Kalau agent bisa dipicu trigger: tambah ke `route_trigger()` **dan** `SUPPORTED_TRIGGERS`
   (API-REFERENCE.md). Dua tempat; lupa salah satu = trigger ditolak 400.
6. Kalau agent memegang approval: tambah timeout yang masuk akal (jangan warisi 300 dtk untuk
   keputusan uang).
7. Uji: `python -m hermes_bridge.smoke --role <Role>` — karakter harus muncul di meja yang benar.
8. Tambah barisnya ke indeks §2 **dan** kartunya di §4.

Yang **tidak** perlu diubah saat menambah agent: `server/index.js`, `validateEvent`,
`officeReducer`, komponen UI. Kalau salah satu terasa perlu, desainnya salah.
