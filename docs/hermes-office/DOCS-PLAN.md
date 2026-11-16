# Hermes Office — Master Docs Plan

Nov 16, 2026 · @Shin · Status pelaksanaan dari rencana 16 dokumen.

**Status: selesai (Rev 3.1).** 16 dari 16 file ada, saling konsisten, dan sudah diperiksa silang.
Dokumen ini menyimpan urutan pengerjaan dan hasil pemeriksaannya, supaya revisi berikutnya punya
jejak.

---

## 1. Daftar & status

| File | Prioritas | Isi | Status |
| --- | --- | --- | --- |
| [README.md](README.md) | 🔴 Wajib | overview, quick start, perbedaan dari base | ✅ |
| [BLUEPRINT.md](BLUEPRINT.md) | 🔴 Wajib | spec teknis Rev 3 + fix Rev 3.1 | ✅ |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 🔴 Wajib | diagram, data flow, tech stack | ✅ |
| [ROOMS.md](ROOMS.md) | 🔴 Wajib | 9 ruangan, navigasi, desk slot map | ✅ |
| [AGENTS.md](AGENTS.md) | 🔴 Wajib | katalog 45 agent | ✅ |
| [PLAN.md](PLAN.md) | 🔴 Wajib | roadmap 10 minggu | ✅ |
| [DB-SCHEMA.md](DB-SCHEMA.md) | 🔴 Wajib | semua tabel SQLite | ✅ |
| [ENV-VARS.md](ENV-VARS.md) | 🔴 Wajib | semua env var | ✅ |
| [API-REFERENCE.md](API-REFERENCE.md) | 🔴 Wajib | REST + WS + slash command | ✅ |
| [DECISIONS.md](DECISIONS.md) | 🟠 Penting | 12 ADR | ✅ |
| [CEO-GUIDE.md](CEO-GUIDE.md) | 🟠 Penting | workflow CEO | ✅ |
| [AGENT-HANDOFFS.md](AGENT-HANDOFFS.md) | 🟠 Penting | protocol + SharedContext | ✅ |
| [SCHEDULER.md](SCHEDULER.md) | 🟡 Opsional | 11 job APScheduler | ✅ |
| [SECURITY.md](SECURITY.md) | 🟡 Opsional | security model | ✅ |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | 🟡 Opsional | setup & gejala | ✅ |
| [CHANGELOG.md](CHANGELOG.md) | 🟡 Opsional | Rev1 → Rev3.1 | ✅ |

Urutan pengerjaan yang dipakai: **pemilik topik lebih dulu** (AGENTS, ROOMS, DB-SCHEMA, ENV-VARS,
API-REFERENCE), lalu dokumen yang menautkannya (ARCHITECTURE, BLUEPRINT, PLAN, README), lalu
dokumen operasional (CEO-GUIDE, HANDOFFS, SCHEDULER, SECURITY, TROUBLESHOOTING, CHANGELOG).

Alasannya: dokumen yang menyebut nama role/tabel/env/endpoint tidak bisa ditulis sebelum nama-nama
itu diputuskan. Rev 3 gagal justru karena beberapa dokumen mengarang nama sendiri.

---

## 2. Aturan satu sumber

| Topik | Pemilik | Dokumen lain |
| --- | --- | --- |
| id ruangan, id desk, koordinat | ROOMS.md | menautkan |
| role key, emoji, warna, tools, trigger | AGENTS.md | menyebut role, bukan config |
| nama tabel & kolom | DB-SCHEMA.md | menyebut nama tabel |
| nama env var | ENV-VARS.md | menyebut nama var |
| endpoint, event, slash command | API-REFERENCE.md | menautkan |
| jadwal job | SCHEDULER.md | menyebut job id |
| angka kebijakan (SLA, grace, refund) | DECISIONS.md §ADR-6 | menautkan |

Kalau sebuah fakta perlu diubah, ubah di pemiliknya. Menyalin fakta ke dua dokumen adalah cara
paling cepat membuat keduanya salah.

---

## 3. Koreksi terhadap rencana awal

Rencana awal (versi sebelum Rev 3.1) memuat beberapa angka yang tidak cocok dengan base. Saat
menulis dokumen ini, angka-angka itu **dihitung ulang dari kode base** dan diganti:

| Di rencana awal | Kenyataan di base | Dokumen sekarang |
| --- | --- | --- |
| Main Office 5×3 slot (15) | 10 spot `spot-1..10` | ROOMS.md: 10 dev + 3 spot bisnis baru |
| Server Room 3×3 slot (9) | 6 spot standing `srv-1..6` | ROOMS.md: 6 MCP + 9 spot bisnis baru |
| Meeting Room "ad-hoc" | 8 kursi `meet-1..8` | ROOMS.md: tetap ad-hoc, dipakai approval/handoff |
| Lunch Room 3×1 slot | 8 lounge `lounge-1..8` | ROOMS.md: tidak dibatasi, dipakai idle |
| 4 ruangan lantai 2 "cukup didaftarkan di officeReducer.ts" | spot & room hidup di `rooms.ts`; reducer hanya event | ROOMS.md §4: perubahan `rooms.ts` + 1 aturan `roomRules.ts` |
| Desk `biz-1..4`, `aw-s1`, `aw-m1`, … | tidak ada spot dengan id itu | AGENTS.md: `biz-b*`, `biz-s*`, `biz-m*`, `biz-c*`, `biz-f*` |
| "Katalog 45 agent" tanpa daftar | 30 bisnis + 12 dev | AGENTS.md: 30 + 15 (12 base + 3 baru) |

Koreksi ini bukan penambahan fitur: semuanya hanya menyamakan dokumen dengan kode yang ada, supaya
implementasi tidak berhenti di "spot tidak ditemukan".

---

## 4. Hasil pemeriksaan silang

Dijalankan setelah semua file ditulis:

| Pemeriksaan | Hasil |
| --- | --- |
| Setiap role di AGENTS.md ada di tabel ruangan ROOMS.md | ✅ 30/30, tidak ada yang dobel |
| Setiap id desk di AGENTS.md ada di ROOMS.md §5 | ✅ 30/30 |
| Setiap tabel yang disebut agent ada di DB-SCHEMA.md | ✅ tickets, user_reports, episode_schedule, subtitle_tracks, payment_events, subscription_status, premium_items, biz_metrics, context, dlq, kb_* |
| Setiap env var yang dipakai kode ada di ENV-VARS.md | ✅ termasuk `KB_MIN_SCORE`, `OLLAMA_URL`, `GOOGLE_REFRESH_TOKEN` |
| Setiap endpoint yang disebut agent ada di API-REFERENCE.md | ✅ `/webhook`, `/approval/*`, `/biz-metrics`, `/event` |
| Setiap job di SCHEDULER.md punya fungsi di §4 | ✅ 11/11 |
| Tidak ada `HERMES_SIDECAR_URL` | ✅ hanya `SIDECAR_URL` |
| Tidak ada contoh CommonJS di dokumen | ✅ `biz-events.js` ESM |
| Konflik nama `SecOps` vs `Security` dijelaskan | ✅ AGENTS.md §1, ADR-7 |
| Semua tautan relatif antar dokumen menunjuk file yang ada | ✅ |
| Angka 30 / 25 / 5 / 15 / 45 konsisten di semua file | ✅ |

---

## 5. Yang sengaja belum ditulis

| Topik | Alasan | Kapan |
| --- | --- | --- |
| Dokumentasi API internal tiap agent (signature fungsi) | berubah paling cepat; docstring di kode lebih akurat | setelah W3 stabil |
| Playbook marketing/konten | itu isi bisnis, bukan arsitektur | di luar lingkup |
| Panduan kontribusi fork | base sudah punya `CONTRIBUTING.md` | kalau ada kontributor kedua |
| Diagram urutan per trigger (13 buah) | ARCHITECTURE.md sudah cukup; 13 diagram akan usang | kalau ada bug alur berulang |

---

## 6. Cara merevisi dokumen ini

1. Ubah file **pemilik** topik.
2. Kalau nama role/tabel/env/endpoint berubah, cari semua kemunculan (`grep -rn "nama-lama" docs/hermes-office/`)
   dan perbarui yang menyebut, bukan yang memiliki.
3. Tambah satu baris di [CHANGELOG.md](CHANGELOG.md).
4. Perbarui tabel §4 di file ini kalau ada pemeriksaan baru.
