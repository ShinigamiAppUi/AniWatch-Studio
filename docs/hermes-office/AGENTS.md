# Hermes Office — Katalog Agent

Nov 16, 2026 · @Shin · Sumber tunggal untuk config, tools, trigger, dan output agent.
Ruangan & id desk: [ROOMS.md](ROOMS.md). Handoff: [AGENT-HANDOFFS.md](AGENT-HANDOFFS.md).

**Total 45 agent** = 30 bisnis (5 generic + 25 AniWatch) + 15 specialist dev (12 base + 3 baru).

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

Catatan Rev 3.1 atas versi Rev 3: `desk` sekarang menunjuk spot yang benar-benar ada di
`rooms.ts` (lihat ROOMS.md), `room` memakai 4 ruangan baru, dan `QAAgent` memakai ✅ supaya tidak
sama dengan `QualityChecker` 🔍 di UI.

### Konflik nama yang harus dijaga

| Nama | Milik | Catatan |
| --- | --- | --- |
| `Security` | dev specialist (`security-auditor`) | **jangan** dipakai agent bisnis |
| `SecOps` | agent bisnis | semua `agent_start("SecOps Agent", "SecOps", …)` |
| `QualityChecker` | AniWatch (kualitas stream) | emoji 🔍 |
| `QAAgent` | premium (kualitas desain) | emoji ✅ |
| `Reviewer` | dev specialist (`code-reviewer`) | bukan agent bisnis |

---

## 2. Kontrak setiap agent

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

## 3. Generic business agents (5)

| Role | Emoji | Tools | Trigger | Output |
| --- | --- | --- | --- | --- |
| **Orchestrator** | 🧠 | `delegate`, `monitor_agents`, `reprioritize`, `escalate_to_human` | semua trigger | koordinasi, satu baris "Delegasi ke X ✓" |
| **Sales** 💼 | 💼 | `qualify_lead`, `draft_email`, `send_email`, `update_crm`, `schedule_meeting` | `new_lead`, `form_submit`, `deal_stage_change` | email terkirim, CRM updated, meeting di kalender |
| **Marketing** 📣 | 📣 | `draft_post`, `schedule_post`, `fetch_analytics`, `generate_report` | `analytics_ready`, `content_schedule`, `weekly_analytics` | konten terpublish, weekly report |
| **Support** 🎧 | 🎧 | `triage_ticket`, `search_kb`, `draft_reply`, `send_reply`, `escalate` | `support_ticket`, `new_email`, SLA breach | tiket resolved / dieskalasi |
| **Ops** ⚙️ | ⚙️ | `check_system`, `run_workflow`, `generate_report`, `send_alert` | `chargeback_received`, error sistem, tiap jam | alert anomali, laporan sistem |

### Support — detail yang mudah salah

Support adalah satu-satunya agent generic yang memakai knowledge base. Alurnya:

```
tiket masuk → triage (kategori + prioritas) → kb.search(subject, top_k=3)
   ├── skor ≥ KB_MIN_SCORE  → draft_reply dari artikel → send_reply
   └── skor <  KB_MIN_SCORE → escalate (ke Orchestrator, lalu manusia)
```

- `KB_MIN_SCORE` (default `0.5`) **relatif** (FTS5 bm25), bukan probabilitas. Kalibrasi ulang
  setelah ≥ 20 artikel; jangan percaya angka default untuk produksi.
- SLA: `received_at + 3600` (1 jam). `check_sla_breaches` (lihat SCHEDULER.md) menagih tiket lewat
  deadline dengan permission card 3 pilihan: *Handle sekarang* / *Extend SLA +30 menit* /
  *Close as resolved*.
- Tiket disimpan di tabel `tickets` (DB-SCHEMA.md), context-nya di `SharedContext` key
  `ticket:<id>`.

---

## 4. AniWatch agents (25)

### 4.1 Core Ops — Server Room, 9 agent

| Role | Emoji | Tools | Trigger | Output |
| --- | --- | --- | --- | --- |
| **Scraper** 🕷️ | 🕷️ | `fetch_source`, `save_episode`, `check_duplicate` | tiap N menit, episode baru | episode baru di DB (belum live) |
| **Metadata** 📋 | 📋 | `fetch_mal`, `fetch_anilist`, `update_db` | setelah Scraper | judul, synopsis, thumbnail, genre, rating |
| **Encoder** 🔄 | 🔄 | `encode_video`, `generate_thumbnail`, `upload_cdn` | file baru masuk | 360p/720p/1080p + thumbnail di CDN |
| **Subtitle** 🌐 | 🌐 | `fetch_subtitle`, `sync_timing`, `detect_encoding` | setelah Encoder | subtitle tersinkron |
| **TranslationAgent** 🌏 | 🌏 | `fetch_raw_subtitle`, `translate_text`, `qa_translation`, `save_translated_sub`, `request_human_review` | setelah Subtitle | sub terjemahan siap attach, atau eskalasi QA |
| **QualityChecker** 🔍 | 🔍 | `check_stream`, `check_subtitle_sync`, `verify_404` | setelah TranslationAgent | report kualitas (lolos / corrupt) |
| **EpisodeScheduler** 📅 | 📅 | `queue_episode`, `check_embargo`, `trigger_publish`, `cancel_schedule` | setelah QC lolos | episode go live tepat waktu, embargo terjaga |
| **Notifier** 🔔 | 🔔 | `push_notif`, `update_rss`, `update_feed` | episode live | subscriber & RSS terupdate |
| **CacheWarmer** ⚡ | ⚡ | `get_trending`, `warm_cdn_cache` | harian 17.00 | CDN hangat sebelum prime time |

**Pipeline episode (sequential, dijaga Orchestrator):**

```
Scraper → Metadata → Encoder → Subtitle → TranslationAgent → QualityChecker
        → EpisodeScheduler ──(embargo habis)──▶ live
        → Notifier + SocialMedia
```

Kegagalan yang sudah dirancang:

| Kejadian | Tindakan |
| --- | --- |
| QC menemukan video corrupt | Orchestrator batalkan pipeline; Scraper coba source alternatif |
| 2x gagal source alternatif | escalate ke manusia ✋ |
| QA terjemahan < `TRANSLATION_QA_THRESHOLD` | permission card: Approve & Lanjutkan / Reject & Translate Ulang |
| DMCA masuk sebelum embargo | `cancel_schedule()` → episode tidak pernah live |

### 4.2 Community — Main Office, 2 agent (+ Support dari generic)

| Role | Emoji | Tools | Trigger | Output |
| --- | --- | --- | --- | --- |
| **Moderator** 🛡️ | 🛡️ | `filter_comment`, `flag_content`, `ban_account` | komentar/report masuk | komentar bersih, akun di-ban |
| **UserReportAgent** 🚨 | 🚨 | `triage_report`, `check_episode_health`, `trigger_qc_pipeline`, `forward_to_support`, `notify_user`, `log_report` | tombol "Laporkan Masalah" | report terklasifikasi, QC di-trigger, user dinotif |

`UserReportAgent` adalah lapisan triage: Support tidak lagi menerima "video rusak". Routing-nya:

```
laporan → triage_report
  ├── technical (video/subtitle/404) → check_episode_health
  │      ├── bermasalah → trigger_qc_pipeline → notify_user
  │      └── normal     → notify_user ("coba clear cache")
  ├── account/billing → forward_to_support → Support 🎧
  └── spam/duplikat   → log_report → selesai
```

### 4.3 Growth — Creative Studio, 5 agent

| Role | Emoji | Tools | Trigger | Output |
| --- | --- | --- | --- | --- |
| **Analytics** 📊 | 📊 | `fetch_watch_data`, `detect_dropoff`, `generate_report` | harian/mingguan | trending + dropoff per episode |
| **SEO** 🔎 | 🔎 | `update_meta`, `update_sitemap`, `add_structured_data` | anime baru ditambah | meta, sitemap, structured data |
| **SocialMedia** 📱 | 📱 | `post_discord`, `post_twitter`, `post_instagram`, `post_telegram` | `announce_episode` | pengumuman terkirim |
| **Recommendation** 🎯 | 🎯 | `fetch_history`, `run_model`, `save_recs` | Minggu 22.00 | rekomendasi personal |
| **Retention** 💌 | 💌 | `segment_users`, `draft_email`, `send_campaign` | `retention_check` | campaign re-engagement |

### 4.4 Premium pipeline — Creative Studio, 5 agent

| Role | Emoji | Tools | Output |
| --- | --- | --- | --- |
| **DesignAgent** 🎨 | 🎨 | `generate_design`, `save_draft` | 3–5 variasi (border/nameplate/effect) |
| **QAAgent** ✅ | ✅ | `check_resolution`, `check_consistency`, `check_transparency` | desain lolos QA saja |
| **PricingAgent** 💰 | 💰 | `analyze_complexity`, `assign_tier` | tier harga |
| **PreviewAgent** 👁️ | 👁️ | `render_mockup`, `bundle_preview` | mockup light + dark |
| **Publisher** 🚀 | 🚀 | `upload_cdn`, `insert_db`, `activate_item` | item live di toko |

Alur dengan **approval gate** di tengah (satu-satunya jalur yang wajib manusia):

```
trigger → DesignAgent → QAAgent → PricingAgent → PreviewAgent
                                    → ✋ approval (Approve / Revisi / Reject)
Approve → Publisher (live)   Revisi → DesignAgent (ulang)   Reject → selesai
```

### 4.5 Finance, Legal, Security — Finance & Legal, 4 agent

| Role | Emoji | Tools | Trigger | Output |
| --- | --- | --- | --- | --- |
| **RevenueTracker** 💵 | 💵 | `record_transaction`, `generate_snapshot`, `detect_anomaly` | payment sukses, harian | laporan revenue |
| **PaymentAgent** 💳 | 💳 | `handle_success`, `handle_failure`, `retry_subscription`, `process_refund`, `flag_chargeback` | `/webhook/payment` | kegagalan bayar tertangani, subscription terjaga |
| **DMCA** ⚖️ | ⚖️ | `verify_request`, `unpublish_episode`, `purge_cdn` | email/legal | takedown + schedule dibatalkan |
| **SecOps** 🔐 | 🔐 | `monitor_events`, `apply_rule`, `escalate` | loop 10 dtk | ancaman terdeteksi + diblokir |

Aturan SecOps (semua ambang, satu tabel):

| Rule | Threshold | Window | Aksi |
| --- | --- | --- | --- |
| `login_attempts` | 5 | 60 dtk | `ban_ip` |
| `concurrent_devices` | 3 | 300 dtk | `soft_lock` |
| `request_rate` | 120 | 60 dtk | `rate_limit` |
| `chargeback_count` | 2 | — | `flag_account` |

PaymentAgent punya aturan sendiri (grace period, retry, refund window) — lihat
[DECISIONS.md](DECISIONS.md) §ADR-6 untuk alasan angkanya, dan [DB-SCHEMA.md](DB-SCHEMA.md)
untuk tabel `payment_events` + `subscription_status`.

---

## 5. Tim dev — 15 specialist

12 dari base + 3 baru untuk AniWatch. Ini **bukan** agent LangGraph: mereka dipanggil oleh chat
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

Routing chat (tambahan di `server/index.js`, pola sama dengan `AGENT_CONFIGS` base):

```js
const ANIWATCH_ROUTING = {
  'player, hls, buffering, kualitas, adaptive, m3u8': 'Player Dev',
  'cdn, encoding, latency, bandwidth, stream, ffmpeg': 'Stream Dev',
  'ios, android, mobile app, react native, flutter':  'Mobile Dev',
}
```

---

## 6. Menambah agent baru

1. Tentukan **ruangan + desk** kosong di [ROOMS.md](ROOMS.md) (kalau tidak ada, tambah spot dulu).
2. Tambah entri di `BUSINESS_AGENT_CONFIGS` — key = role string, warna unik, emoji belum dipakai.
3. Buat `hermes_bridge/agents/<nama>.py` dengan kontrak §2.
4. Daftarkan tools-nya di deskripsi agent (string tool **harus** sama dengan yang dipanggil).
5. Kalau agent bisa dipicu trigger: tambah ke `route_trigger()` **dan** `SUPPORTED_TRIGGERS`
   (API-REFERENCE.md). Dua tempat; lupa salah satu = trigger ditolak 400.
6. Kalau agent memegang approval: tambah timeout yang masuk akal (jangan warisi 300 dtk untuk
   keputusan uang).
7. Uji: `python -m hermes_bridge.smoke --role <Role>` — karakter harus muncul di meja yang benar.
8. Tambah barisnya ke tabel di dokumen ini.

Yang **tidak** perlu diubah saat menambah agent: `server/index.js`, `validateEvent`,
`officeReducer`, komponen UI. Kalau salah satu terasa perlu, desainnya salah.
