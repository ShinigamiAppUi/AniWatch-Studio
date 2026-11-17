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

### W4 — Webhook + scheduler

- FastAPI sidecar `127.0.0.1:8765`
- `SUPPORTED_TRIGGERS` + validasi secret; semua trigger lewat Orchestrator
- APScheduler: 11 job (SCHEDULER.md) — 7 inti, termasuk `cleanup_shared_context`; sisanya sweep approval, handoff check, publish embargo, dan backup

**Deliverable:** trigger dari luar (curl) memunculkan Orchestrator lalu agent yang tepat.

**Kriteria terima:** 13 trigger diuji satu per satu; tidak ada yang jatuh ke fallback `ops` kecuali
yang memang dirancang; `cleanup_shared_context` terbukti menghapus baris > 24 jam (uji dengan
`ts` mundur).

### W5 — Support + Community

- Support dengan KB SQLite FTS5, minimal 20 artikel FAQ
- Subtitle + Moderator + **UserReportAgent**
- SLA tracking + `check_sla_breaches` (satu approval, bukan dua)

**Deliverable:** tiket dari email/form dijawab dari KB atau dieskalasi; laporan user dirutekan.

**Kriteria terima:** laporan teknis → QC pipeline ter-trigger + user dinotif; laporan akun →
diteruskan ke Support; tiket lewat SLA memunculkan **satu** card dengan 3 opsi.

---

## Fase 3 — Growth & Product (W6–W7)

### W6 — Growth

- Analytics, SEO, SocialMedia, Recommendation, Retention
- SocialMedia tersambung ke akhir pipeline episode

**Deliverable:** episode baru otomatis diumumkan ke Discord/Telegram.

**Kriteria terima:** satu episode live menghasilkan satu post Discord + satu post Telegram dalam
< 60 detik; Recommendation batch jalan Minggu 22.00 dan menulis rekomendasinya ke DB AniWatch
(di luar fork ini — fork hanya memantulkan karakternya di kantor).

### W7 — Premium pipeline

- DesignAgent → QAAgent → PricingAgent → PreviewAgent → ✋ approval → Publisher
- `premium_items` + `/design`, `/pending-items`, `/approve`

**Deliverable:** satu item premium dari generate sampai `live` di toko.

**Kriteria terima:** Reject menghentikan pipeline, Revisi mengulang dari DesignAgent, Approve
men-deploy; approval dari card dan dari `/approve` menghasilkan status yang sama.

---

## Fase 4 — Koordinasi & Bisnis (W8–W10)

### W8 — Orchestrator + handoff

- `build_orchestrator_graph()` + `route_trigger()` 13 trigger
- `SharedContext` + protocol handoff (AGENT-HANDOFFS.md)

**Deliverable:** agent bisa saling oper context, bukan hanya dipanggil Orchestrator.

**Kriteria terima:** Sales → Marketing → Support berantai tanpa kehilangan context (tiga karakter
muncul berurutan, `handoff:*` terisi lalu dibaca); pipeline episode dan rantai sales sama-sama
lulus.

### W9 — Finance, Legal, Security

- RevenueTracker, PaymentAgent, DMCA, SecOps
- `/webhook/payment` dengan verifikasi SHA-512

**Deliverable:** kegagalan bayar tertangani otomatis dan bisa diaudit.

**Kriteria terima:** tiga skenario PaymentAgent lulus: renewal gagal → grace 3 hari → downgrade;
refund → card → approve/tolak; chargeback → item dicabut + SecOps dinotif. DMCA membatalkan
schedule yang belum live.

### W10 — Dashboard + polish

- `BizMetricsPanel.tsx` + `OrchestratorCard.tsx`
- SLA + metrics live, semua slash command terdaftar
- CacheWarmer + Retention scheduler aktif
- Backup harian (DB-SCHEMA.md §13)

**Deliverable:** kantor siap dipakai harian oleh CEO.

**Kriteria terima:** checklist [BLUEPRINT.md](BLUEPRINT.md) §11 dicentang semua, dan satu hari
operasional penuh (pagi analytics → siang episode → malam report) berjalan tanpa campur tangan
manual kecuali approval.

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
- [ ] `python -m compileall hermes_bridge webhook_server` bersih
- [ ] Tidak ada `except: pass` baru
- [ ] Env baru tercatat di ENV-VARS.md, tabel baru di DB-SCHEMA.md, endpoint baru di API-REFERENCE.md
- [ ] Satu baris di CHANGELOG.md
