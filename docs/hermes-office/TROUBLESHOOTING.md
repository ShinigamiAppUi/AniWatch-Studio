# Hermes Office — Troubleshooting

Nov 16, 2026 · @Shin · Gejala → sebab → perbaikan. Kalau tidak ada di sini, cek log sidecar dulu
(`scheduler job ...`, `office down, event queued`), baru buka kode.

---

## 0. Tiga perintah pertama untuk masalah apa pun

```bash
npm run doctor                              # port, token, permission, hook
curl -s http://127.0.0.1:3334/health        # kantor hidup?
curl -s http://127.0.0.1:8765/health        # sidecar hidup?
```

Kalau `doctor` sudah merah, jangan lanjut membaca bagian lain — perbaiki itu dulu.

---

## 1. Karakter bisnis tidak muncul sama sekali

| Sebab | Cek | Perbaikan |
| --- | --- | --- |
| `role` tidak cocok config | log: `agent_spawned` terkirim? `curl /agents` | samakan string dengan key `BUSINESS_AGENT_CONFIGS` (AGENTS.md) |
| Token salah/kedaluwarsa | `curl -H "Authorization: Bearer $OFFICE_TOKEN" -X POST .../event` → 401 | ambil ulang `~/.agent-office/auth-token`, restart bridge |
| Bridge jalan tanpa `.env` | log bridge kosong, 401 berulang | jalankan lewat sidecar atau `set -a; source .env; set +a` |
| Event masuk DLQ | `sqlite3 ~/.hermes-office/dlq.db 'select count(*) from dlq'` | nyalakan kantor; flusher mengirim ulang dalam 30 dtk |
| Ruangan/desk tidak ada | log browser: spot tidak ditemukan | cek `desk` di config vs ROOMS.md §5 |
| Reducer tidak mengenal role | karakter tidak muncul walau `/agents` memuatnya | pastikan case `agent_spawned` bercabang ke `BUSINESS_AGENT_CONFIGS` |

**Diagnosis cepat:** kirim satu event manual.

```bash
TOKEN=$(cat ~/.agent-office/auth-token)
curl -s -X POST http://127.0.0.1:3334/event \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"type":"agent_spawned","agent":{"id":"scraper-test","name":"Scraper","role":"Scraper","task":"Test"}}'
```

Karakter muncul → masalahnya di Python. Tidak muncul → masalahnya di config/UI.

---

## 2. Karakter muncul, lalu langsung hilang / diam

| Sebab | Perbaikan |
| --- | --- |
| `agent_done` terkirim dua kali | satu `agent_done` per `agent_start`; bungkus `try/finally` sekali |
| Exception sebelum `agent_update` | log Python menunjukkan traceback; perbaiki, jangan telan dengan `except: pass` |
| `agentId` berbeda antar event | pakai nilai balik `agent_start`; jangan membuat id sendiri |
| Approval menggantung | timeout belum jalan; cek `wait_for_approval` timeout wajar (300 dtk) |

---

## 3. Approval card tidak bisa dijawab / agent tidak lanjut

```
UI klik Allow → WS approval_response → biz-events.js → POST /approval-callback → store
                                                                                  ↓
                                                        agent polling GET /approval/{id}
```

Cek satu per satu:

1. **Card muncul?** Kalau tidak: `agent_waiting` tidak terkirim (urutannya salah — harus sebelum
   polling).
2. **WS mengirim?** Buka devtools → WS frame `approval_response` ada?
3. **Sidecar menerima?** Log sidecar: `POST /approval-callback 200`. Kalau `ECONNREFUSED`, sidecar
   mati atau `SIDECAR_URL` salah (harus `http://127.0.0.1:8765`).
4. **Agent polling?** Log agent: `GET /approval/...` tiap 3 dtk. Kalau tidak ada, agent macet di
   tempat lain.
5. **Keputusan hilang?** Store one-shot: kalau ada dua poller untuk `agent_id` yang sama, yang satu
   mendapat nilainya, yang lain `null` → **jangan** spawn dua agent untuk satu task.

---

## 4. `require is not defined` di `biz-events.js`

Proyek ini ESM (`"type": "module"`). Semua `server/*.js` memakai `import`/`export`. Kalau muncul
error ini, file ditulis dengan gaya CommonJS (bug Rev 3 yang sudah diperbaiki). Ganti ke `import`
dan `export`, dan pakai `import { registerBizRoutes } from './biz-events.js'` (dengan `.js`).

---

## 5. Event hilang saat kantor mati

Itu perilaku yang dirancang — tapi hanya kalau DLQ bekerja. Cek:

```bash
sqlite3 ~/.hermes-office/dlq.db "select id, attempts, last_err, substr(payload,1,80) from dlq limit 10"
```

| Temuan | Arti | Tindakan |
| --- | --- | --- |
| ada baris, `attempts` naik terus | kantor masih mati / token salah | nyalakan kantor, cek token |
| ada baris `attempts >= 10` | menyerah | perbaiki penyebab, lalu kirim manual |
| tabel kosong padahal ada kejadian | `_post` tidak pernah gagal (mungkin 200 tapi ditolak logika) | cek log server, bukan bridge |
| baris `biz_metrics` dobel | flusher memakai `_post` (bug Rev 3.1 #5) | pakai `_send_once` di flusher |

Manual replay satu baris:

```bash
sqlite3 ~/.hermes-office/dlq.db "select payload from dlq where id=1" > /tmp/p.json
curl -s -X POST http://127.0.0.1:3334/event -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' --data-binary @/tmp/p.json
```

---

## 6. Webhook ditolak

| Kode | Sebab | Perbaikan |
| --- | --- | --- |
| 403 | `X-Webhook-Secret` beda | samakan dengan `WEBHOOK_SECRET`, restart sidecar |
| 400 `trigger type tidak dikenal` | tidak ada di `SUPPORTED_TRIGGERS` | tambah di set **dan** di `route_trigger()` |
| 422 | body bukan `{type, data}` | `data` wajib object |
| 500 | exception di Orchestrator | log sidecar punya traceback; route tidak dikenal jatuh ke `ops` |

---

## 7. Sidecar tidak mau start

| Pesan | Sebab | Perbaikan |
| --- | --- | --- |
| `WEBHOOK_SECRET env var wajib diset!` | `.env` tidak dimuat | jalankan dari root project, atau `set -a; source .env` |
| `MIDTRANS_SERVER_KEY env var wajib diset!` | idem | isi nilai (boleh dummy panjang kalau belum ada Midtrans) |
| `address already in use` | sidecar lama masih hidup | `lsof -i :8765`, hentikan proses itu (bukan semua proses python) |
| job jalan dobel tiap interval | `--reload` + `start_scheduler()` saat import | pindahkan ke lifespan (SCHEDULER.md §3) |

---

## 8. Episode tidak go live

```
/schedule            → daftar antrian + status
/embargo <id>        → status + cancel_reason
```

| `status` | Arti | Tindakan |
| --- | --- | --- |
| `scheduled` | menunggu embargo | normal; cek `embargo_until` masuk akal (epoch, bukan ms) |
| `live` | sudah tayang | — |
| `cancelled` | DMCA / manual | `cancel_reason` menjelaskan |
| `failed` | error saat publish | log EpisodeScheduler punya exception |

Kalau tidak ada baris sama sekali: QC belum memanggil `schedule_episode`, atau pipeline berhenti di
TranslationAgent/QualityChecker. Lihat karakter terakhir yang muncul di Server Room.

Kesalahan klasik: `embargo_until` diisi **milidetik** (`Date.now()`) padahal skema memakai **detik**
(`time.time()`). Episode akan "due" 50 tahun kemudian.

---

## 9. Terjemahan selalu minta review

`qa_translation` mengembalikan skor < `TRANSLATION_QA_THRESHOLD` (0.75). Cek:

1. Provider benar? `TRANSLATION_PROVIDER=deepl` tapi `DEEPL_API_KEY` kosong → skor rendah/0.
2. Nama karakter tidak konsisten di glossary → QA menurunkan skor berkali-kali. Tambah glossary.
3. Threshold terlalu tinggi untuk bahasa target. Turunkan ke 0.65 **hanya** setelah memeriksa 10
   sampel manual.

---

## 10. Support selalu eskalasi (atau menjawab ngawur)

| Gejala | Sebab | Perbaikan |
| --- | --- | --- |
| selalu eskalasi | KB kosong / skor di bawah `KB_MIN_SCORE` | isi KB ≥ 20 artikel: `python -m hermes_bridge.kb.ingest ./docs/` |
| menjawab artikel salah | `KB_MIN_SCORE` terlalu rendah | naikkan; FTS5 bm25 bersifat relatif, kalibrasi dengan data nyata |
| `sqlite3.OperationalError: no such table: kb_articles` | `schema.sql` dibaca relatif ke CWD | pakai `Path(__file__).parent / "schema.sql"` |
| `database is locked` | dua proses menulis `kb.db` | satu penulis (sidecar); ingest dijalankan saat sidecar berhenti |

---

## 11. UI berat / frame drop

| Sebab | Perbaikan |
| --- | --- |
| Terlalu banyak agent aktif | batasi 12 bersamaan di Orchestrator |
| SecOps mengirim event tiap 10 dtk tanpa pelanggaran | kirim event hanya saat ada pelanggaran |
| `biz_metric_update` tiap tool call | kirim per task selesai atau tiap 60 dtk |

---

## 12. Port / proses

```bash
ss -ltnp | grep -E '3333|3334|8765'      # siapa memegang port
lsof -i :3334                            # detail proses
npm run stop                             # scripts/stop-office.sh (kantor saja)
```

Jangan pernah mematikan proses berdasarkan pola nama (`pkill -f python`): bisa mematikan sidecar,
skrip setup, atau proses lain di mesin yang sama.

---

## 13. Hasil `doctor` yang sering muncul

| Baris | Arti | Perbaikan |
| --- | --- | --- |
| `server ... refused` | kantor belum start | `bash scripts/start-office.sh` |
| `token ... missing` | `auth-token` belum dibuat | jalankan server sekali |
| `token ... mode 644` | permission longgar | `chmod 600 ~/.agent-office/auth-token` |
| `hooks ... not installed` | Claude Code tidak mengirim event | `npm run install-hooks` |
| `assets ... missing` | background ruangan lantai 2 salah path | `npm run check-assets` |

---

## 14. Kalau semua terlihat benar tapi tetap aneh

1. Restart sidecar (bukan seluruh mesin) — scheduler dan store approval ikut bersih.
2. Buka kantor dengan `npm run open` (membawa token UI). Tanpa token, card tidak bisa dijawab dan
   chat tidak bisa dikirim — sering dikira bug.
3. Periksa jam sistem. Jadwal, embargo, SLA, dan TTL semuanya memakai waktu lokal/epoch; jam yang
   meleset 1 jam membuat semua "telat" atau "belum waktunya".
