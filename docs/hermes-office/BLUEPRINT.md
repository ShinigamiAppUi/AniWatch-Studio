# Hermes Office — Blueprint Teknis (Rev 3.1)

Nov 16, 2026 · @Shin · Status: **siap implementasi**

Dokumen ini adalah spec teknis. Ia **tidak** mengulang isi file lain: kode lengkap tiap modul
tinggal di file topiknya (lihat tabel "Batas modul"). Yang ada di sini: konsep, batas sistem,
daftar modul, daftar fix, dan aturan konsistensi yang mengikat semuanya.

---

## 1. Konsep

Hermes Office adalah fork `W17ant/Claude-Office` (v1.2.0, MIT, React + Express + SQLite) yang
diperluas untuk menampung **dua tim** dalam satu kantor virtual:

- **Tim Dev** — sudah ada di base, zero config. Sumber event: Claude Code hooks. Karakter: satu
  Claude per session terminal + subagent specialist. 12 specialist routing + 3 baru (Player,
  Stream, Mobile Dev).
- **Tim Bisnis** — ditambahkan di fork ini. Sumber event: `hermes_bridge.py`. 30 agent
  (5 generic + 25 AniWatch), dijalankan LangGraph + Hermes via Ollama.

Filosofi base tidak berubah: **kantor adalah cermin apa yang agent sedang lakukan**, bukan
dashboard terpisah. Setiap event (spawn, tool call, selesai, error, menunggu) langsung terpantul
sebagai animasi karakter.

---

## 2. Batas sistem

| Di dalam fork ini | Di luar (tidak disentuh / hanya dipanggil) |
| --- | --- |
| `hermes_bridge/` seluruhnya | Repo AniWatch (DB produksi, CDN, player) — diakses lewat tool agent |
| `webhook_server/` seluruhnya | Midtrans, Gmail, HubSpot, Discord/Telegram API |
| `server/biz-events.js` (baru) | `server/index.js` bagian base (hanya 2 baris disisipkan) |
| `src/types.ts` (tambahan config) | Seluruh komponen UI base |
| `src/rooms.ts` (4 ruangan baru) | Logika walk/pathfinding base (`walk.ts`, `roomTransfer.ts`) |
| `src/components/BizMetricsPanel.tsx`, `OrchestratorCard.tsx` | Desktop app, LAN mode, phone mode |

Aturan: kalau sebuah perubahan menyentuh lebih dari **dua baris** di file base selain
`server/index.js`, itu tanda desainnya salah — cari jalan lewat `biz-events.js` atau event biasa.

---

## 3. Batas modul (single source of truth)

| Topik | File | Jangan ditulis di tempat lain |
| --- | --- | --- |
| Topologi, port, diagram alur | [ARCHITECTURE.md](ARCHITECTURE.md) | — |
| 9 ruangan, id desk, kapasitas | [ROOMS.md](ROOMS.md) | AGENTS.md hanya menautkan |
| Config + tool + trigger tiap agent | [AGENTS.md](AGENTS.md) | BLUEPRINT tidak menyalin |
| Semua tabel SQLite | [DB-SCHEMA.md](DB-SCHEMA.md) | agent hanya menyebut nama tabel |
| Semua REST/WS/slash command | [API-REFERENCE.md](API-REFERENCE.md) | agent hanya menyebut nama endpoint |
| Semua env var | [ENV-VARS.md](ENV-VARS.md) | kode hanya `os.getenv` |
| Protocol handoff + SharedContext | [AGENT-HANDOFFS.md](AGENT-HANDOFFS.md) | — |
| Job scheduler | [SCHEDULER.md](SCHEDULER.md) | — |
| Model keamanan | [SECURITY.md](SECURITY.md) | — |

---

## 4. Yang sudah ada di base — pakai langsung

| Komponen | Detail |
| --- | --- |
| UI kantor | Isometric pixel art, React 18 + TS + Vite, 5 ruangan |
| Server | Express 4 + `ws`, port 3334, SQLite `better-sqlite3` |
| Dev hooks | `hooks/agent-tracker.sh` + `.py`, `status-line.sh`, `install-hooks.sh` |
| Chat panel | Slack-style, history di SQLite, AI via `claude -p` |
| Routing dev | `AGENT_CONFIGS` di `src/types.ts` (12 specialist + MCP) |
| Whiteboard | Task list nyata dari Claude Code |
| Meters | Cost/payroll, token/menit, context fill |
| Permission card | Allow / Allow & remember / Deny dari UI |
| Prod Is Down | Deploy gagal → kantor merah + postmortem |
| Inspector | Klik karakter → tool, token, model, transkrip |
| Seasons | 4 musim + 4 hari besar |
| Phone mode | `npm run lan` → QR |
| Desktop app | Electron + auto-update |
| Slash commands | `/status`, `/agents`, `/recap`, `/incident`, `/all-clear`, `/the-office` |
| Security | Bind 127.0.0.1, token Bearer, request hook ditandatangani |

## 5. Gap yang harus dibangun

| Gap | Dampak kalau tidak dibangun | Ditutup oleh |
| --- | --- | --- |
| Business agent role | Karakter bisnis tidak punya config → tidak muncul | `src/types.ts` (AGENTS.md) |
| `hermes_bridge.py` | Tidak ada jembatan Hermes → Express | §6 |
| Webhook + scheduler | Agent hanya bisa dipicu manual | `webhook_server/` (SCHEDULER.md) |
| Knowledge base Support | Support tidak bisa jawab dari FAQ | `hermes_bridge/kb/` |
| Business metrics | Tidak ada padanan meters untuk tim bisnis | `BizMetricsPanel.tsx` |
| Orchestrator | Tidak ada koordinasi antar agent | `hermes_agents/orchestrator.py` |
| Handoff protocol | Sales tidak bisa oper context ke Marketing/Support | AGENT-HANDOFFS.md |
| Dead-letter queue | Event hilang saat server mati | `queue.py` |
| Approval callback | Agent Python tidak tahu keputusan user | `approval.py` + `biz-events.js` |
| 4 ruangan lantai 2 | 30 agent bisnis berdesakan di 5 ruangan dev | ROOMS.md |

---

## 6. Modul yang dibangun

### 6.1 Bridge (`hermes_bridge/bridge.py`)

Satu-satunya titik kontak Python → Express. Kontraknya:

| Fungsi | Event/endpoint | Kapan |
| --- | --- | --- |
| `agent_start(name, role, task)` | `agent_spawned` → `POST /event` | agent mulai |
| `agent_update(id, status, tool)` | `agent_working` | tiap tool call |
| `agent_waiting(id, msg, options)` | `agent_waiting` | sebelum polling approval (lihat fix Rev 3.1 #8) |
| `wait_for_approval(id, timeout)` | `GET {SIDECAR}/approval/{id}` tiap 3 dtk | setelah card tampil |
| `agent_done(id, result)` | `agent_completed` | task selesai |
| `agent_error(id, err, retrying)` | `agent_working` + `failed: true` | gagal / retry |
| `update_biz_metrics(delta)` | `POST /biz-metrics` | tiap task selesai / tiap N menit |

Aturan wajib:

1. **Retry:** 3 percobaan, backoff `0.5 * 2^attempt`. Habis itu → DLQ, bukan `raise`.
2. **Timeout HTTP:** 2 detik. Kantor yang lambat tidak boleh menghentikan pipeline bisnis.
3. **DLQ:** payload gagal masuk SQLite `~/.hermes-office/dlq.db`, flusher mencoba ulang tiap 30
   detik, maksimal 50 baris per putaran. Payload `biz_metrics` di-replay ke `/biz-metrics`,
   bukan ke `/event` (fix Rev 3 #2).
4. **Role string harus persis** key di `BUSINESS_AGENT_CONFIGS` (AGENTS.md). Typo = karakter tidak
   muncul tanpa error apa pun.

Kode lengkap: lihat "Lampiran kode" di [API-REFERENCE.md](API-REFERENCE.md) §bridge dan
[DB-SCHEMA.md](DB-SCHEMA.md) §dlq.

### 6.2 Sidecar (`webhook_server/`)

FastAPI di `127.0.0.1:8765`, tiga tanggung jawab:

- **`POST /webhook`** — trigger dari luar, divalidasi `X-Webhook-Secret` + `SUPPORTED_TRIGGERS`,
  lalu **selalu** diteruskan ke `run_orchestrator_async` (fix Rev 3 #4).
- **`GET /approval/{agent_id}` + `POST /approval-callback`** — store keputusan user (one-shot).
- **`POST /webhook/payment`** — notifikasi Midtrans, diverifikasi SHA-512 (fix Rev 3 #7/#9).

Scheduler APScheduler hidup di proses yang sama: lihat [SCHEDULER.md](SCHEDULER.md).

### 6.3 Express tambahan (`server/biz-events.js`)

ESM (base memakai `"type": "module"` — lihat fix Rev 3.1 #1). Dua fungsi:

- `registerBizRoutes(app, db, broadcast)` → tabel `biz_metrics`, `POST /biz-metrics`, `GET /biz-metrics`.
- `handleBizWsMessage(ws, data)` → meneruskan `approval_response` dari UI ke sidecar.

Disisipkan ke `server/index.js`: satu baris `registerBizRoutes(...)` saat startup dan satu baris
`handleBizWsMessage(ws, data)` di handler pesan WebSocket.

### 6.4 Frontend tambahan

- `src/types.ts` — 30 entri `BUSINESS_AGENT_CONFIGS` (AGENTS.md), plus `BizMetrics` type.
- `src/rooms.ts` — 4 `RoomId` baru + spot bisnis (ROOMS.md).
- `src/officeReducer.ts` — dua case baru: `agent_spawned` memilih jalur bisnis vs dev,
  `biz_metric_update` menulis `state.bizMetrics`.
- `BizMetricsPanel.tsx`, `OrchestratorCard.tsx` — komponen kecil, membaca state, tanpa fetch sendiri.

---

## 7. Event baru

| Event | Dikirim saat | Visual |
| --- | --- | --- |
| `agent_spawned` | agent bisnis mulai | karakter muncul dari pintu, jalan ke meja |
| `agent_working` | tiap tool call | speech bubble update |
| `agent_completed` | selesai | jempol 👍, jalan ke pintu, keluar |
| `agent_working` (`failed: true`) | error/retry | bubble merah ❌ |
| `agent_waiting` | menunggu approval | bubble ✋ + kartu tombol |
| `biz_metric_update` | tiap task / interval | meters bisnis update |

Bentuk payload **sama** dengan event dev (`agent`, `agentId`, `status`, `tool`, `result`, `error`),
jadi `validateEvent` base tidak perlu diubah. Detail field: [API-REFERENCE.md](API-REFERENCE.md).

---

## 8. Alur satu task (end-to-end)

```
1. Trigger masuk       webhook / APScheduler / chat manual
2. Orchestrator        route_trigger() → pilih agent
3. agent_spawned       karakter muncul di ruangan sesuai ROOMS.md
4. LangGraph loop      tiap tool: agent_working  (+ update_biz_metrics di akhir tool berat)
5. Butuh manusia?      agent_waiting → card ✋ → poll 3 dtk, timeout sesuai task
6. Selesai             agent_completed → 👍 → keluar lewat pintu
   Gagal               agent_error → retry sekali → kalau gagal lagi, escalate
```

Nomor 5 adalah satu-satunya jalur dua arah. Detail callback: [API-REFERENCE.md](API-REFERENCE.md)
§approval, dan [CEO-GUIDE.md](CEO-GUIDE.md) untuk sisi manusianya.

---

## 9. Daftar fix Rev 3 (dari Rev 2) — dipertahankan

| # | Fix | Letak |
| --- | --- | --- |
| 🔴 1 | `check_sla_breaches` tidak lagi double `wait_for_approval` | hermes_agents/support.py |
| 🟠 2 | `update_biz_metrics` POST ke `/biz-metrics`, tidak lewat `/event` | bridge.py |
| 🟠 3 | `SIDECAR_URL` konsisten (bukan `HERMES_SIDECAR_URL`) | biz-events.js, bridge.py |
| 🟠 4 | Webhook tidak melewati Orchestrator | webhook_server/main.py |
| 🟠 5 | Scheduler bisnis lewat Orchestrator | webhook_server/scheduler.py |
| 🟠 6 | `cleanup_older_than()` dijadwalkan 03.00 | scheduler + shared_context.py |
| 🟠 7 | `MIDTRANS_SERVER_KEY` dijaga `RuntimeError` saat startup | webhook_server/main.py |
| 🟡 8 | `MIDTRANS_SERVER_KEY` masuk tabel env utama | ENV-VARS.md |
| 🟡 9 | `hashlib.sha512` explicit `utf-8` + `.get()` default `''` | webhook_server/main.py |
| ➕ | `TranslationAgent` 🌏 + `UserReportAgent` 🚨 (total 30) | AGENTS.md |

## 10. Fix Rev 3.1 (dari Rev 3) — revisi dokumen ini

Rev 3 punya beberapa ketidakkonsistenan yang membuat implementasi mentok. Semua sudah diperbaiki
di dokumen ini; angka ini yang berlaku, bukan Rev 3.

| # | Masalah di Rev 3 | Perbaikan |
| --- | --- | --- |
| 🟠 1 | `server/biz-events.js` memakai `require`/`module.exports`, padahal `package.json` base `"type": "module"` dan seluruh `server/*.js` memakai `import`. File ini akan langsung crash. | Ditulis ulang sebagai ESM (`import`/`export`), lihat API-REFERENCE.md §biz-events. |
| 🟠 2 | Desk string di `BUSINESS_AGENT_CONFIGS` (`biz-1`, `aw-s1`, `aw-m1`, …) tidak menunjuk ke spot mana pun di `rooms.ts`; 30 agent bisnis juga dijejalkan ke 3 ruangan dev (6 spot server room untuk 9 core ops). | Peta ruangan & desk dihitung ulang terhadap art base + 4 ruangan lantai 2. Satu tabel di [ROOMS.md](ROOMS.md); config agent di [AGENTS.md](AGENTS.md) memakai id itu. |
| 🟠 3 | `bridge._post(...)` dipanggil langsung dari `check_sla_breaches` dan `translation_agent` (fungsi privat, mudah berubah). | Tambah `agent_waiting(agent_id, message, options)` publik di bridge; semua agent memakai itu. |
| 🟡 4 | Di `queue.py`, `_post_metrics` memakai `__import__("httpx")`; `OFFICE_TOKEN` dibaca ulang dari env walau bridge sudah punya konstan. | Import modul di atas file, satu sumber konfigurasi dari `bridge.py`. |
| 🟡 5 | `_post` yang retry lalu `_dlq.push(payload)` bisa berputar: flusher memanggil `_post` lagi, gagal, push lagi → baris DLQ berlipat. | Flusher memakai `_send_once` (tanpa push), dan `push` memakai `INSERT` dengan kunci payload+ts unik. |
| 🟡 6 | `start_scheduler()` dipanggil saat import `main.py` → `uvicorn --reload` menjalankan dua scheduler (job dobel). | Dipindah ke `lifespan`/`startup` event FastAPI, dengan guard `scheduler.running`. |
| 🟡 7 | Ambang FTS5 `0.5` dipakai sebagai angka pasti padahal `bm25` relatif. | Threshold jadi env `KB_MIN_SCORE`, default `0.5`, wajib dikalibrasi setelah 20 artikel (AGENTS.md §Support). |
| 🟡 8 | Tabel `biz_metrics` hanya punya key/value global; `BizMetricsPanel` butuh `today`/`sla`/`agents_active`, dan tidak ada cara reset harian. | Skema diperluas + kolom `day`; `GET /biz-metrics` mengembalikan bentuk yang dibaca panel. Lihat DB-SCHEMA.md. |
| 🟡 9 | Dokumen menyebut 45 agent tanpa daftar tunggal; angka 30/12/15 tersebar. | Satu tabel 45 agent di [AGENTS.md](AGENTS.md) (30 bisnis + 15 dev). |
| 🟡 10 | `TranslationAgent` timeout approval 1 jam, refund 24 jam, tapi `approval.py` tidak punya TTL — store bisa tumbuh. | TTL store 24 jam + sweep di scheduler (SCHEDULER.md). |

---

## 11. Checklist sebelum production

Fondasi & keamanan
- [ ] `OFFICE_TOKEN`, `WEBHOOK_SECRET`, `MIDTRANS_SERVER_KEY` hanya dari env (SECURITY.md)
- [ ] Semua env opsional ada di `.env.example`
- [ ] Sidecar bind `127.0.0.1`, bukan `0.0.0.0`

Bridge & event
- [ ] DLQ aktif, flusher jalan, replay `biz_metrics` benar
- [ ] `approval_response` dari UI sampai ke store sidecar
- [ ] `biz-events.js` ESM dan ter-load (tidak ada `require is not defined`)

Trigger
- [ ] Semua webhook lewat Orchestrator, `SUPPORTED_TRIGGERS` lengkap + `user_report`
- [ ] `check_new_emails` & `run_marketing_report` lewat Orchestrator
- [ ] `cleanup_shared_context` + `sweep_approvals` terjadwal

Agent
- [ ] KB ≥ 20 artikel, threshold dikalibrasi
- [ ] Orchestrator route 13 trigger tanpa fallback ke `ops`
- [ ] Semua `agent_start` role persis key config
- [ ] Nama `SecOps` (bukan `Security`) untuk agent bisnis
- [ ] Pipeline episode dengan embargo jalan penuh termasuk TranslationAgent
- [ ] `cancel_schedule` diuji: DMCA sebelum embargo → tidak pernah go live

Premium & payment
- [ ] Approval gate premium: generate → approve → live
- [ ] `/webhook/payment` diuji dengan simulator Midtrans
- [ ] Renewal gagal → grace → downgrade diuji
- [ ] Refund → approval card → approve/tolak diuji

Frontend & docs
- [x] `BizMetricsPanel` menampilkan data live (`src/components/BizMetricsPanel.tsx`)
- [x] `OrchestratorCard` menampilkan alur trigger + tabel handoff resmi
      (`src/components/OrchestratorCard.tsx`); `run_orchestrator` + protokol handoff ada di
      `hermes_agents/orchestrator.py` dan `hermes_bridge/handoff.py` (W8)
- [ ] Slash command baru terdaftar di chat routing
- [ ] `npm run doctor` semua green
