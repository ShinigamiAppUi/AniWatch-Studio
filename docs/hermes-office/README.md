# Hermes Office

Kantor virtual pixel-art untuk **dua tim dalam satu gedung**: tim dev yang sudah built-in di
[W17ant/Claude-Office](https://github.com/W17ant/Claude-Office), dan tim bisnis AniWatch yang
dijalankan oleh **Hermes (Nous Research) via LangGraph**.

Nov 16, 2026 · @Shin · Status dokumen: **Rev 3.1** (lengkap, siap implementasi)

> Dokumen ini adalah titik masuk. Semua detail teknis ada di file sebelah — lihat
> [Daftar Dokumen](#daftar-dokumen) di bawah. Tidak ada yang diulang di dua tempat;
> kalau satu topik disebut di dua file, file pertama adalah sumbernya dan yang kedua menautkannya.

---

## Apa yang dibangun

Base repo ini (`@w17ant/agent-office` v1.2.0) memvisualisasikan **Claude Code**: hook → Express →
WebSocket → React. Karakter muncul, duduk, bicara, selesai, keluar. Fork ini **menambah satu jalur
baru di sisi kiri** server yang sama:

```
CRM / Form ──webhook──┐
APScheduler ──────────┤
Chat manual ──────────┤
                      ▼
              hermes_bridge.py ──▶ Express :3334 ──WebSocket──▶ React :3333
              (Python, LangGraph)        │
                                    approval callback ◀── FastAPI :8765
```

Yang **tidak** berubah: semua UI, animasi, karakter, 5 ruangan, meters dev, permission card,
desktop app, phone mode. Express server tidak pernah tahu bedanya agent Claude Code dan agent
Hermes — keduanya masuk lewat `POST /event` yang sama.

---

## Perbedaan dari base

| Aspek | Base (Claude-Office) | Hermes Office |
| --- | --- | --- |
| Sumber event | Claude Code hooks (bash/Python) | hooks **+** `hermes_bridge.py` (Python/LangGraph) |
| Agent | Claude per session + 12 specialist dev | **+ 30 agent bisnis** (5 generic + 25 AniWatch) |
| Ruangan | 5 (main, corridor, meeting, server, lunch) | **9** (5 base + 4 di lantai 2) |
| Trigger | hanya dari Claude Code | **+** webhook, APScheduler, chat manual |
| Otak agent | Claude Code CLI (`claude -p`) | Hermes via Ollama (`nous-hermes-2`) |
| Dashboard | meters dev (cost, token, context) | **+** `BizMetricsPanel` (leads, tiket, SLA) |
| Ketahanan event | `except: pass` (event hilang) | retry 3x + **dead-letter queue** SQLite |
| Approval | hanya permission Claude Code | **+** approval gate agent bisnis (2 arah) |
| Koordinasi | routing chat per specialist | **+** Orchestrator LangGraph + handoff context |

---

## Requirements

| Komponen | Versi minimum | Kenapa |
| --- | --- | --- |
| Node.js | **20** (`engines.node: ">=20"`) | base menolak versi lebih lama saat install |
| npm | 9+ | lockfile v3 |
| Python | 3.11+ | `str \| None` di bridge, `slots`/typing modern |
| Ollama | latest, jalan di `127.0.0.1:11434` | inference Hermes lokal |
| Model Ollama | `nous-hermes-2` (`HERMES_MODEL`) | bisa diganti model Hermes lain |
| SQLite | 3.35+ dengan FTS5 | knowledge base Support (FTS5 bawaan Python 3.11 aman) |
| Claude Code CLI | opsional | hanya kalau tim dev ikut dijalankan |

```bash
ollama pull nous-hermes-2
ollama serve
```

Cek FTS5 sekali di awal: `python3 -c "import sqlite3;print(sqlite3.sqlite_version)"`.

---

## Quick start (fork)

```bash
# 1. base kantor — harus hijau dulu sebelum apa pun ditambah
npm install
npm run doctor                 # semua cek harus green
npm run install-hooks

# 2a. UI + server sekaligus (dev)
npm run dev:all                # Express :3334 + Vite :3333

# 2b. atau cara base: server saja, UI dari hasil build
bash scripts/start-office.sh   # lalu `npm run open` (membawa token UI)
```

`npm run dev` **hanya** menjalankan Vite (UI); tidak ada Express di `:3334`, jadi event akan gagal
dikirim. Untuk kantor lengkap pakai `dev:all`, `server`, atau `start-office.sh`.

```bash
# 3. sisi bisnis (Python 3.11+)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# 4. token kantor — BUKAN dibuat sendiri, ini isi file milik server
echo "OFFICE_TOKEN=$(cat "${AGENT_OFFICE_HOME:-$HOME/.agent-office}/auth-token")" >> .env

# 5. sidecar webhook + scheduler (WAJIB 127.0.0.1)
uvicorn webhook_server.main:app --host 127.0.0.1 --port 8765

# 6. bukti bahwa jembatan hidup
python -m hermes_bridge.smoke --all      # 30 karakter muncul di meja yang benar
python -m hermes_bridge.smoke --approval # card ✋ muncul; klik Allow; script lanjut
```

`OFFICE_TOKEN` **tidak dibuat sendiri** — kalau diisi nilai karangan, semua `POST /event` dijawab
401 dan event masuk DLQ tanpa karakter muncul. Lihat [ENV-VARS.md](ENV-VARS.md).

Urutan pengerjaan lengkap: [PLAN.md](PLAN.md). Kalau ada yang gagal: [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

---

## Struktur project

```
hermes-office/
├── src/                          # React + TS (base), hanya 3 file yang disentuh
│   ├── types.ts                  # ← EDIT: + BUSINESS_AGENT_CONFIGS (30 role)
│   ├── rooms.ts                  # ← EDIT: + 4 RoomId lantai 2, spot bisnis
│   ├── officeReducer.ts          # ← EDIT: agent_spawned bercabang, biz_metric_update
│   └── components/
│       ├── BizMetricsPanel.tsx   # ← BARU: meters bisnis
│       └── OrchestratorCard.tsx  # ← BARU: status orchestrator
│
├── server/                       # Express + ws + better-sqlite3 (base)
│   ├── index.js                  # ← EDIT: 2 baris (registerBizRoutes, handleBizWsMessage)
│   ├── biz-events.js             # ← BARU: ESM, /biz-metrics + forward approval
│   └── chat-db.js                # base: ~/.agent-office/chat.db (0600)
│
├── hermes_agents/                # ← BARU: pipeline episode (W3), support + kb + user_report (W5)
├── hermes_bridge/                # ← BARU: Python bridge
│   ├── bridge.py                 # event → Express, retry, DLQ
│   ├── queue.py                  # dead-letter queue SQLite
│   ├── shared_context.py         # state antar agent (thread-safe)
│   ├── db.py                     # koneksi + schema hermes.db
│   ├── handoff.py                # envelope handoff
│   └── smoke.py                  # uji jembatan tanpa Hermes
│
│   (agent-nya ada di hermes_agents/: support.py, kb.py, user_report.py; 30 role di AGENTS.md)
│
├── webhook_server/               # ← BARU: FastAPI sidecar (127.0.0.1:8765)
│   ├── main.py                   # /webhook, /approval/*, /webhook/payment, /health
│   ├── scheduler.py              # APScheduler (lihat SCHEDULER.md)
│   └── approval.py               # store keputusan (one-shot, TTL 24 jam)
│
├── requirements.txt              # ← BARU
├── .env.example                  # ← BARU
└── docs/hermes-office/           # ← BARU: 16 dokumen (folder ini)
```

Data runtime di luar repo: `~/.agent-office/` (token, chat.db) dan `~/.hermes-office/`
(`hermes.db`, `dlq.db`, `shared.db`, `kb.db`). Detail: [DB-SCHEMA.md](DB-SCHEMA.md).

---

## Daftar Dokumen

16 file, semuanya sudah ada dan saling konsisten. Kolom "Sumber" menunjukkan di mana detail
teknis topik itu tinggal — jangan duplikasi ke file lain.

| File | Prioritas | Isi | Sumber untuk |
| --- | --- | --- | --- |
| [README.md](README.md) | 🔴 | Overview, requirements, quick start, struktur | — |
| [BLUEPRINT.md](BLUEPRINT.md) | 🔴 | Spec teknis penuh Rev 3 + semua fix Rev 3.1 | daftar fix, batas modul |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 🔴 | Diagram sistem, data flow, tech stack | topologi & port |
| [ROOMS.md](ROOMS.md) | 🔴 | 9 ruangan, pintu, desk slot map | id ruangan & id desk |
| [AGENTS.md](AGENTS.md) | 🔴 | Katalog 45 agent: config, kartu, alur kerja | config tiap agent |
| [PLAN.md](PLAN.md) | 🔴 | Roadmap 10 minggu (Fase 1–4) | urutan kerja |
| [DB-SCHEMA.md](DB-SCHEMA.md) | 🔴 | Semua tabel SQLite terpusat | nama tabel & kolom |
| [ENV-VARS.md](ENV-VARS.md) | 🔴 | Semua env var: tipe, default, wajib/opsional | nama env |
| [API-REFERENCE.md](API-REFERENCE.md) | 🔴 | REST + WebSocket + slash command | endpoint & event |
| [DECISIONS.md](DECISIONS.md) | 🟠 | ADR: alasan di balik pilihan besar | "kenapa begitu" |
| [CEO-GUIDE.md](CEO-GUIDE.md) | 🟠 | Workflow CEO: approval, dashboard, command | cara pakai harian |
| [AGENT-HANDOFFS.md](AGENT-HANDOFFS.md) | 🟠 | Protocol handoff + SharedContext | kontrak antar agent |
| [SCHEDULER.md](SCHEDULER.md) | 🟡 | Semua job APScheduler, timing, dependensi | jadwal & job |
| [SECURITY.md](SECURITY.md) | 🟡 | Security model (token, binding, signature) | aturan keamanan |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | 🟡 | Masalah setup umum + solusi | gejala → sebab |
| [CHANGELOG.md](CHANGELOG.md) | 🟡 | Rev1 → Rev2 → Rev3 → Rev3.1 | riwayat keputusan |

Rencana penulisan & status per file: [DOCS-PLAN.md](DOCS-PLAN.md).

---

## Prinsip yang tidak boleh dilanggar

1. **Jangan sentuh base lebih dari yang perlu.** UI, animasi, karakter, 5 ruangan, meters dev: utuh.
2. **Business event adalah event biasa.** Semua lewat `POST /event`, bukan jalur kedua.
3. **Bridge itu tipis.** `hermes_bridge` hanya menerjemahkan state LangGraph → format event kantor.
   Logic bisnis tetap di agent.
4. **Reliability dulu.** Event tidak boleh hilang karena kantor mati: retry + DLQ.
5. **Satu trigger, satu pintu.** Semua trigger bisnis masuk lewat Orchestrator (Fix 4/5 di
   [BLUEPRINT.md](BLUEPRINT.md)), bukan memanggil agent langsung dari webhook/scheduler.

Alasan di balik prinsip-prinsip ini: [DECISIONS.md](DECISIONS.md).
