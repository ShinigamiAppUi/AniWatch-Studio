# Hermes Office — Architecture

Nov 16, 2026 · @Shin · Turunan dari [BLUEPRINT.md](BLUEPRINT.md)

Dokumen ini menjawab satu pertanyaan: **proses apa jalan di mana, bicara ke siapa, lewat port apa.**
Isi tiap modul ada di file topiknya.

---

## 1. Topologi proses

```
┌───────────────────────────── mesin yang sama (loopback) ─────────────────────────────┐
│                                                                                      │
│  Claude Code ──hooks──┐                                                              │
│  (terminal dev)       │                                                              │
│                       ▼                                                              │
│                  ┌─────────────┐   WebSocket    ┌──────────────────┐                 │
│                  │  Express    │◀──────────────▶│  React (Vite)    │                 │
│                  │  :3334      │                │  :3333           │                 │
│                  │  ws + SQLite│                └──────────────────┘                 │
│                  └──────┬──────┘                        ▲                             │
│                         │ POST /event (Bearer)          │ approval_response           │
│                         │                               │                             │
│  ┌──────────────────────┴───────────────────────┐       │                             │
│  │  hermes_bridge (Python, in-process agent)    │       │                             │
│  │  bridge.py · queue.py · shared_context.py    │       │                             │
│  │  agents/*.py (LangGraph + Hermes/Ollama)     │       │                             │
│  └──────┬───────────────────────────┬───────────┘       │                             │
│         │ GET /approval/{id}        │ HTTP tool calls    │                             │
│         ▼                           ▼                    │                             │
│  ┌─────────────────────┐     ┌──────────────┐           │                             │
│  │ FastAPI sidecar     │────▶│  Dunia luar  │           │                             │
│  │ :8765               │     │ Gmail, Midtrans,           │                             │
│  │ webhook + scheduler │     │ HubSpot, Discord,          │                             │
│  │ + approval store    │     │ Telegram, CDN, Ollama      │                             │
│  └─────────▲───────────┘     └──────────────┘           │                             │
│            │ POST /approval-callback                     │                             │
│            └──────────── server/biz-events.js ───────────┘                             │
│                                                                                      │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

Semua listener **loopback**. Tidak ada port bisnis yang menghadap jaringan. Aturan lengkap:
[SECURITY.md](SECURITY.md).

---

## 2. Port & proses

| Proses | Port | Start | Wajib jalan? |
| --- | --- | --- | --- |
| Vite dev (UI) | 3333 (`AGENT_OFFICE_UI_PORT`) | `npm run dev` / `start-office.sh` | dev saja |
| Express + WS | 3334 (`AGENT_OFFICE_PORT`) | `npm run server` | **ya** — tanpa ini tidak ada kantor |
| FastAPI sidecar | 8765 | `uvicorn webhook_server.main:app` | ya, untuk trigger & approval |
| Ollama (Hermes) | 11434 (default Ollama) | `ollama serve` | ya, kalau agent memakai LLM lokal |
| Electron | — | `npm start` | tidak (pilihan tampilan) |

`AGENT_OFFICE_PORT` dibaca oleh server, hook, `doctor`, Vite, dan desktop app — satu export
memindahkan seluruh kantor.

---

## 3. Tech stack

| Layer | Teknologi | Catatan |
| --- | --- | --- |
| Frontend | React 18 + TypeScript 5 + Vite 5 | dari base, tidak diubah |
| Server | Express 4 + `ws` + `better-sqlite3` | dari base; tambah `biz-events.js` |
| Bridge | Python 3.11 + `httpx` 0.27 | tipis, tanpa framework |
| Sidecar | FastAPI 0.111 + Uvicorn 0.30 | bind 127.0.0.1 |
| Scheduler | APScheduler 3.10 (BackgroundScheduler) | di proses sidecar |
| Agent | LangGraph 0.1.14 + Hermes (`nous-hermes-2`) via Ollama | logic bisnis di sini |
| KB | SQLite FTS5 (default) / Chroma 0.5 (opsional) | lihat AGENTS.md §Support |
| Antrian gagal | SQLite `~/.hermes-office/dlq.db` | lihat DB-SCHEMA.md §dlq |
| Integrasi luar | Gmail API, Google Calendar, HubSpot/Notion, Midtrans, Discord, Telegram, X | env di ENV-VARS.md |

---

## 4. Data flow

### 4.1 Satu event kantor (dev maupun bisnis)

```
producer                     Express :3334                      React
   │                              │                                │
   │ POST /event {type, agent}    │                                │
   ├─────────────────────────────▶│ validateEvent                  │
   │                              │ sanitise (clamp tiap field)    │
   │                              │ processEvent → event           │
   │ ◀── 200 {ok} ────────────────│ broadcast(event) ─────────────▶│ dispatch ke officeReducer
   │                              │ tasks.noteEvent / health       │
```

Karena bisnis memakai event yang sama, **tidak ada** perubahan pada validator, sanitizer, atau
reducer dev. Yang baru hanya dua case di reducer (`agent_spawned` bercabang, `biz_metric_update`).

### 4.2 Trigger bisnis

```
webhook / scheduler / chat manual
        │
        ▼
post /webhook (FastAPI)  ── validate secret + trigger type
        │
        ▼
run_orchestrator_async() ── 1 karakter Orchestrator muncul
        │
        ▼
route_trigger() ── pilih node LangGraph
        │
        ├── sales / marketing / support / ops / scraper / analytics /
        │   social_media / retention / user_report
        ▼
agent node ── agent_start → agent_working (per tool) → agent_done / agent_error
        │
        └── kalau butuh manusia: agent_waiting → poll approval → lanjut
```

### 4.3 Approval (satu-satunya jalur dua arah)

```
Agent Python            Express :3334            React UI           Sidecar :8765
    │                        │                      │                    │
    │ POST /event            │                      │                    │
    │  agent_waiting ───────▶│───── broadcast ─────▶│ card ✋             │
    │                        │                      │ user klik Approve   │
    │ GET /approval/{id} ────┼──────────────────────┼───────────────────▶│
    │  (tiap 3 dtk)          │◀── approval_response ┘                    │
    │                        │  biz-events.js forward ──────────────────▶│ set_approval()
    │ ◀── {decision} ────────┼───────────────────────┼────────────────────│
    │ lanjut                 │                      │                    │
```

Timeout polling **wajib** ada di sisi agent (default 300 dtk, refund 24 jam, terjemahan 1 jam).
Kalau habis: `agent_error(..., retrying=False)` dan task masuk antrian manusia, bukan menggantung.

### 4.4 Event hilang (DLQ)

```
_post gagal 3x → queue.push(payload) → SQLite dlq.db
                         ▲                    │
                         │         flusher tiap 30 dtk (maks 50 baris)
                         │                    ▼
                    gagal lagi ────── _send_once(payload) ── sukses ──▶ DELETE baris
```

Payload `biz_metrics` di-replay ke `/biz-metrics`; payload lain ke `/event`. Skema:
[DB-SCHEMA.md](DB-SCHEMA.md).

---

## 5. Ruangan sebagai lapisan navigasi

Kantor bukan satu gambar: 5 ruangan base + 4 ruangan baru, semuanya terhubung lewat koridor
(star topology). Agent tidak pernah "teleport"; perpindahan = pintu sendiri → koridor → pintu
tujuan. Event tidak membawa posisi — **ruangan ditentukan config role** (`room` di
`BUSINESS_AGENT_CONFIGS`), lalu `roomRules.ts` memutuskan kapan agent pindah (mis. ke meeting room
saat menunggu approval). Peta lengkap: [ROOMS.md](ROOMS.md).

---

## 6. Di mana state tinggal

| State | Tempat | Umur |
| --- | --- | --- |
| Chat & session dev | SQLite base (`messages`, …) | persisten |
| Metrics bisnis | tabel `biz_metrics` (DB yang sama) | persisten, per hari |
| Antrian event gagal | `~/.hermes-office/dlq.db` | sampai terkirim |
| Context antar agent | `~/.hermes-office/shared.db` | 24 jam (cleanup 03.00) |
| Keputusan approval | memori sidecar | one-shot, TTL 24 jam |
| Knowledge base | `~/.hermes-office/kb.db` | persisten |
| State UI | memori React | hilang saat reload (snapshot dari server) |

---

## 7. Kegagalan yang dirancang, bukan kebetulan

| Kalau ini mati | Yang terjadi | Yang tetap jalan |
| --- | --- | --- |
| Express | Event masuk DLQ, UI tidak update | Agent bisnis lanjut (tidak blocking) |
| Sidecar | Trigger & approval mati; agent yang sedang menunggu timeout | Event kantor & agent yang tidak butuh approval |
| Ollama | Agent gagal di langkah LLM → `agent_error` | Semua yang deterministik (encoding, upload, query DB) |
| Kantor + sidecar | Pipeline bisnis tetap jalan sendiri | — (kantor hanya cermin) |

Prinsip: **kantor tidak pernah menjadi dependency pipeline.** Ini ADR-3 di [DECISIONS.md](DECISIONS.md).
