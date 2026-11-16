# Hermes Office — Panduan CEO

Nov 16, 2026 · @Shin · Untuk manusia yang memakai kantor, bukan yang menulis kodenya.

Kantor ini bukan dashboard. Ia menunjukkan **apa yang sedang dikerjakan agent**, dan satu-satunya
hal yang benar-benar perlu kamu lakukan adalah **menjawab kartu yang mengangkat tangan ✋**.

---

## 1. Rutinitas harian (15 menit)

| Waktu | Yang kamu lihat | Yang kamu lakukan |
| --- | --- | --- |
| Pagi | `📊 Tim Bisnis Hari Ini` di panel | baca 4 angka: leads, email, tiket, SLA breach |
| Pagi | karakter di Server Room | kalau kosong padahal ada episode baru, pipeline berhenti — cek `/schedule` |
| Siang | kartu ✋ (approval) | putuskan (lihat §3) |
| Sore | karakter di Creative Studio | pipeline premium berjalan; tidak perlu diapa-apakan |
| Malam | `/biz` di chat | satu pesan ringkasan; kalau ada angka aneh, `/tickets` atau `/reports` |

Aturan praktis: **jangan memantau terus-menerus.** Kalau ada yang butuh kamu, kartu muncul dan
suaranya berbunyi. Semua yang tidak memunculkan kartu memang dirancang untuk jalan sendiri.

---

## 2. Membaca kantor

| Yang terlihat | Artinya |
| --- | --- |
| Karakter muncul dari pintu, jalan ke meja | task baru dimulai |
| Speech bubble berubah-ubah | agent sedang memanggil tool |
| Tangan naik ✋, kartu muncul | **butuh kamu** (satu-satunya yang blocking) |
| Bubble merah, karakter geleng | error; kalau retry berhasil, ia lanjut sendiri |
| Jempol 👍 lalu jalan ke pintu | task selesai, karakter keluar |
| Karakter pindah ke Meeting Room | approval / rapat / handoff |
| Karakter di Lunch Room | idle lama — normal |
| Dua karakter berhadapan | handoff (AGENT-HANDOFFS.md) |

Klik karakter mana pun → inspector: task, tool yang dipanggil, token, model, potongan transkrip.
Ini cara tercepat menjawab "kenapa ini lambat".

---

## 3. Approval — satu-satunya keputusanmu

Lima jenis kartu yang akan kamu lihat. Semuanya punya tombol, bukan pertanyaan bebas.

| Kartu | Muncul saat | Pilihan | Kalau timeout |
| --- | --- | --- | --- |
| **Refund** | user minta refund dalam 7 hari | Approve Refund / Tolak / Minta Info Lebih | 24 jam → antrian manual |
| **Premium item** | desain siap jual | Approve / Revisi / Reject | pipeline berhenti, item tetap `pending_approval` |
| **Terjemahan** | QA sub < threshold | Approve & Lanjutkan / Reject & Translate Ulang | 1 jam → ditolak, perlu retry manual |
| **SLA breach** | tiket lewat 60 menit | Handle sekarang / Extend SLA +30 menit / Close as resolved | 2 menit → dicatat, tiket tetap terbuka |
| **Eskalasi** | agent gagal 2x | Retry / Batalkan / Serahkan ke manusia | tidak ada; task menunggu |

Cara memutuskan dengan cepat:

- **Refund:** lihat nominal dan alasan di kartu. Di bawah 7 hari + alasan wajar → Approve. Di luar
  window, agent sudah menolak otomatis — kalau kartunya tetap muncul, itu pengecualian, pikirkan
  sendiri.
- **Premium:** lihat preview light + dark di kartu. Yang kamu nilai: apakah terlihat jelas di HP
  (bukan di monitor 27"). Revisi kalau ragu — satu putaran desain lebih murah daripada item jelek
  yang sudah live.
- **Terjemahan:** baca 2–3 baris sampel di kartu. Kalau nama karakter konsisten dan tidak ada
  kalimat yang jelas salah, Approve. Kalau ragu, Reject lebih aman (sub bisa diperbaiki, episode
  jelek sudah ditonton).
- **SLA:** "Extend" hanya kalau kamu memang akan menanganinya dalam 30 menit. Kalau tidak,
  "Handle sekarang" lebih jujur.

Kartu juga bisa dijawab dari HP (`npm run lan` → scan QR), dan approval premium bisa lewat chat:
`/approve [id]`.

---

## 4. Slash command yang kamu pakai

| Kebutuhan | Command |
| --- | --- |
| Ringkasan hari ini | `/biz` |
| Uang | `/revenue`, `/payments`, `/subscriptions`, `/refunds`, `/chargeback` |
| Pelanggan | `/tickets`, `/sla`, `/reports`, `/report-stats` |
| Konten | `/schedule`, `/translations`, `/pending-items` |
| Keamanan | `/security`, `/incidents`, `/unban [ip/user]` |

Detail tiap command: [API-REFERENCE.md](API-REFERENCE.md) §6. Semua menjawab dalam satu pesan
pendek — kalau butuh angka lebih dalam, buka panel metrics atau minta agent menyiapkan laporan.

---

## 5. Tiga hal yang tidak perlu kamu lakukan

1. **Menjalankan pipeline manual.** Pipeline episode, premium, dan analytics punya jadwal sendiri.
   Kalau macet, itu bug — laporkan, jangan tambal dengan manual berulang.
2. **Menjawab semua tiket.** Support menjawab dari KB; yang sampai ke kamu sudah yang tidak bisa
   dijawab KB.
3. **Menjaga kantor tetap terbuka.** Kantor boleh ditutup; agent bisnis tetap jalan dan event masuk
   antrian, tampil saat kantor dibuka lagi.

---

## 6. Insiden

| Gejala | Langkah pertama |
| --- | --- |
| Kantor merah "Prod Is Down" | itu event deploy dev, bukan bisnis — lihat `/incident` |
| Tidak ada karakter bisnis sama sekali | cek sidecar hidup (`/health`), lalu `OFFICE_TOKEN` (ENV-VARS.md) |
| Karakter muncul tapi tidak bergerak | tool call macet; inspector menunjukkan tool yang menggantung |
| Kartu ✋ tidak bisa diklik | server UI token hilang — buka ulang dari `npm run open` |
| Bayaran gagal beruntun | `/payments`; kalau pola sama, cek `/webhook/payment` (signature) |
| Episode tidak live padahal jadwal lewat | `/embargo [episode_id]`; kalau `cancelled`, ada DMCA |

Langkah teknis lengkap: [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

---

## 7. Review mingguan (Senin, 30 menit)

1. `/biz` → bandingkan dengan minggu lalu.
2. `/sla` → breach harus turun; kalau naik, tambah artikel KB untuk pertanyaan yang paling sering.
3. `/report-stats` → episode mana yang paling banyak dilaporkan; kalau satu episode mendominasi,
   QC-nya bermasalah, bukan usernya.
4. `/topselling` → item mana yang layak dibuat sekuel.
5. `/security` → hanya perlu reaksi kalau ada pola baru (bukan satu-dua percobaan login).

Yang dicatat: satu paragraf. Kalau butuh lebih dari satu paragraf, berarti ada keputusan produk
yang harus diambil, bukan laporan.
