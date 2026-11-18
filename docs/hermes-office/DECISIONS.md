# Hermes Office — Architecture Decision Records

Nov 16, 2026 · @Shin · Satu ADR = satu keputusan yang mahal untuk diubah. Kalau ragu, baca ini
sebelum "memperbaiki" sesuatu yang terlihat aneh.

Format: **Konteks → Keputusan → Konsekuensi → Alternatif yang ditolak.**

---

## ADR-1 — Fork, bukan repo baru

**Konteks.** Base `W17ant/Claude-Office` sudah punya UI pixel-art, animasi, permission card,
desktop app, dan 900+ test. Membangun ulang kantor dari nol berarti berbulan-bulan hanya untuk
mencapai paritas visual.

**Keputusan.** Fork, dan perlakukan base sebagai **produk jadi**: semua yang visual tidak diubah.
Perubahan di file base dibatasi dua baris di `server/index.js` plus tambahan aditif di `types.ts`
dan `rooms.ts`.

**Konsekuensi.** Upgrade base di masa depan tetap mungkin (perubahan kita sedikit dan terisolasi).
Sebaliknya, kita harus menerima cara base memodelkan agent: satu karakter per `agent_spawned`,
state di `officeReducer`, dan event lewat satu endpoint. Fork ini **tidak** boleh menambah konsep
baru di UI.

**Ditolak.** Repo baru dari template; embed kantor sebagai iframe di dashboard terpisah (melanggar
filosofi "kantor = cermin, bukan dashboard").

---

## ADR-2 — Agent bisnis deterministik dulu; LLM Hermes/Ollama belum diimplementasikan

**Konteks.** Tim dev memakai Claude Code karena itu alat kerjanya. Tim bisnis butuh agent yang
jalan otomatis dari webhook, tanpa terminal, tanpa manusia mengetik prompt.

**Keputusan yang berlaku di kode hari ini.** Agent bisnis di `hermes_agents/` adalah kode
**deterministik**: aturan, SQLite, dan HTTP ke layanan luar. Tidak ada panggilan LLM dan tidak ada
LangGraph. Satu node = satu agent; Orchestrator adalah graph pendek di atas `dict`
(`hermes_agents/orchestrator.py`, `MAX_HOPS = 4`) yang memilih node, dan kerja antar agent dibawa
oleh handoff di SharedContext.

**Yang belum dikerjakan.** ADR ini semula memutuskan LangGraph + LLM **Hermes**
(`nous-hermes-2`) via Ollama lokal. Itu **belum diimplementasikan**: tidak ada kode yang memanggil
Ollama, `HERMES_MODEL` dan `OLLAMA_URL` belum dibaca siapa pun, dan `langgraph` sengaja tidak ada
di `requirements.txt`. Kalau nanti ditambahkan, ADR ini diperbarui lebih dulu, dan setiap keputusan
berisiko uang atau publikasi tetap lewat **approval gate**, bukan diserahkan ke LLM.

**Konsekuensi hari ini.** Nol biaya inference, dan hasilnya bisa diuji offline serta diulang persis
(itu yang diuji `hermes_agents/selfcheck.py`). Batasnya: agent tidak punya penalaran bebas — setiap
keputusan harus bisa dihitung ulang dari payload/DB, jadi skor, triage dan moderasi berbasis aturan
yang alasannya ikut ditulis di hasil.

**Ditolak.** Memanggil `claude -p` untuk agent bisnis (butuh sesi CLI, mahal per task, tidak bisa
di-schedule); satu framework agent pihak ketiga (menambah dependensi yang tidak dipakai base).

---

## ADR-3 — Kantor tidak pernah jadi dependency pipeline

**Konteks.** Kalau Express mati dan pipeline bisnis ikut mati, kantor berubah dari "cermin" menjadi
"single point of failure".

**Keputusan.** Semua event kantor bersifat **fire-and-forget** dengan retry 3x lalu DLQ. Tidak ada
satu pun langkah bisnis yang menunggu jawaban Express. Satu-satunya pengecualian: approval, dan
bahkan itu punya timeout yang berakhir dengan eskalasi, bukan menggantung.

**Konsekuensi.** Event bisa terlambat tampil (DLQ flush 30 dtk), tapi tidak pernah hilang, dan
pipeline tetap benar saat kantor mati. Debugging jadi dua lapis: log bisnis dan log kantor.

**Ditolak.** Blocking POST sampai 200 (pipeline mati saat kantor down); in-memory queue (hilang saat
proses restart).

---

## ADR-4 — SQLite untuk semuanya, Chroma opsional

**Konteks.** Data yang ada: chat, metrics, tiket, jadwal episode, payment, knowledge base. Volume
kecil (satu bisnis, bukan SaaS multi-tenant), satu mesin.

**Keputusan.** SQLite di semua tempat. Itu sudah pilihan base (`better-sqlite3`) dan Python tidak
butuh server tambahan. Knowledge base default **SQLite FTS5** (bm25), Chroma hanya kalau butuh
semantic search dan sudah diukur bahwa FTS5 kurang.

**Konsekuensi.** Satu file = satu backup. Tidak ada operasi jaringan untuk query. Batasnya: penulisan
paralel terbatas (WAL + `check_same_thread=False` + lock), dan pencarian hanya berbasis kata
(FTS5 tidak paham sinonim).

**Ditolak.** Postgres (server tambahan, tidak ada gunanya di satu mesin); Chroma sebagai default
(dependensi besar, embedding butuh model, belum terbukti lebih baik untuk FAQ 20 artikel).

---

## ADR-5 — Business event memakai format event dev

**Konteks.** Base punya `validateEvent`, sanitizer, reducer, dan test untuk event dev. Menambah tipe
event bisnis berarti menyentuh semuanya.

**Keputusan.** Agent bisnis mengirim `agent_spawned` / `agent_working` / `agent_completed` /
`agent_error` dengan bentuk payload yang sama. Hanya `agent_waiting` dan `biz_metric_update` yang
benar-benar baru, dan keduanya aditif.

**Konsekuensi.** Nol perubahan di validator; semua test dev tetap berlaku. Batasnya: field khusus
bisnis tidak boleh ditambahkan ke event (mis. `episodeId`). Kalau perlu, taruh di `status` (string
bebas) atau di DB.

**Ditolak.** Tipe event `biz_*` terpisah (menduplikasi reducer & validator, memecah inspector).

---

## ADR-6 — Angka kebijakan payment & SLA

**Konteks.** Butuh angka konkret supaya implementasi tidak menebak. Angka ini kebijakan bisnis, bukan
temuan teknis.

| Kebijakan | Angka | Alasan |
| --- | --- | --- |
| Grace period subscription | 3 hari | cukup untuk kartu kedaluwarsa yang diperbarui, tidak cukup untuk "menunggu uang masuk" |
| Retry renewal maksimal | 2x | lebih dari itu = gagal bayar sungguhan, bukan insiden |
| Downgrade | ke `free`, item tidak dicabut | mencabut item setelah bayar = keluhan, bukan pencegahan |
| Refund window | 7 hari | standar toko digital; di atas itu keputusan manual |
| SLA tiket | 60 menit | tim kecil, tiket kebanyakan pertanyaan berulang yang dijawab KB |
| SLA extend | +30 menit per approval | satu kali; extend kedua = eskalasi manusia |
| Timeout approval default | 5 menit | cukup untuk CEO melihat HP; lebih lama = pipeline tertahan |
| Timeout approval refund | 24 jam | keputusan uang tidak boleh dipaksa cepat |
| Timeout approval terjemahan | 1 jam | review sub butuh membaca, bukan menekan tombol |
| `KB_MIN_SCORE` | 0.5 (relatif) | titik awal; **wajib** dikalibrasi ulang |
| Retensi SharedContext | 24 jam | handoff selesai dalam menit; sehari lebih dari cukup |

**Konsekuensi.** Semua angka ada di satu tabel; kalau bisnis berubah, ubah di sini **dan** di kode.
Angka yang tersebar di beberapa file adalah bug dokumentasi.

---

## ADR-7 — `SecOps`, bukan `Security`

**Konteks.** Tim dev sudah punya specialist `Security` (`security-auditor`) di chat routing. Agent
bisnis dengan nama sama akan membuat `@Security` ambigu dan bisa memunculkan karakter yang salah.

**Keputusan.** Agent bisnis keamanan bernama **`SecOps`**, key `SecOps`, tampilan "SecOps Agent".

**Konsekuensi.** Satu nama tambahan untuk dihafal, dan semua `agent_start` harus memakai `SecOps`.
Kalau suatu saat dev specialist di-rename, keputusan ini tetap aman.

**Ditolak.** Memakai `Security` dan membedakan lewat prefix ruangan (rapuh: routing chat berbasis
teks, bukan ruangan).

---

## ADR-8 — Lantai 2 dengan art yang dipakai ulang

**Konteks.** 30 agent bisnis tidak muat di 5 ruangan base tanpa berebut meja dengan dev (server room
base hanya punya 6 spot, core ops butuh 9). Membuat pixel art baru berarti pekerjaan seni besar dan
merusak konsistensi visual.

**Keputusan.** Empat ruangan baru di lantai 2 dengan **background yang sama** (business-suite ←
meeting-room, creative-studio ← main-office, finance-legal ← server-room, exec-floor ←
meeting-room). Hanya `agentSpots`, `connections`, dan `entryPoint` yang baru.

**Konsekuensi.** Kantor terasa lebih besar tanpa satu pun aset baru. Risikonya: dua ruangan terlihat
identik — diterima, karena lantai berbeda dan isinya berbeda. Semua spot bisnis memakai id sendiri,
jadi tidak ada tabrakan dengan spot dev.

**Ditolak.** Satu ruangan raksasa untuk 30 agent (tidak terbaca, dan kamera tidak muat); membagi
agent bisnis ke spot dev (dev kehilangan mejanya).

---

## ADR-9 — Approval satu arah: card dulu, poll kemudian

**Konteks.** Agent Python butuh keputusan manusia. UI hanya tahu WebSocket; Python hanya bisa HTTP.

**Keputusan.** Agent **mengirim** `agent_waiting` (card muncul), lalu **polling** `GET
/approval/{id}` tiap 3 detik. UI mengirim `approval_response` lewat WS; `biz-events.js` meneruskannya
ke sidecar; store sidecar `pop` sekali.

**Konsekuensi.** Tidak ada WebSocket di sisi Python (tidak perlu dependensi baru). Latensi maksimal
3 detik. Batasnya: dua agent tidak boleh memakai `agent_id` yang sama, dan store adalah memori
sidecar — restart sidecar = keputusan yang belum diambil hilang (dan agent akan timeout, itu benar).

**Ditolak.** Callback HTTP langsung dari Express ke agent (agent tidak punya server); long-poll
sampai 5 menit (proxy/timeout rapuh, lebih sulit di-debug).

---

## ADR-10 — Satu pemuat `.env`: sidecar

**Konteks.** Bridge, agent, scheduler, dan Express semuanya butuh env. Beberapa proses memuat `.env`
sendiri = nilai berbeda antar proses (mis. `SIDECAR_URL` salah di satu tempat — bug Rev 3 #3).

**Keputusan.** Hanya `webhook_server/main.py` yang memanggil `load_dotenv()`. Bridge dan agent
membaca `os.getenv` dan **selalu dijalankan** oleh sidecar (in-process) atau skrip yang sudah
`source .env`. Express tidak butuh `.env` sama sekali (hanya `AGENT_OFFICE_*`).

**Konsekuensi.** Satu sumber nilai; `SIDECAR_URL` mustahil berbeda antar proses. Batasnya: menjalankan
`bridge.py` mandiri tanpa `source .env` akan gagal 401 — pesan errornya harus jelas.

**Ditolak.** `load_dotenv()` di setiap modul (nilai bisa saling menimpa); `.dev.vars` (file kedua
yang membingungkan).

---

## ADR-11 — Trigger hanya dua pintu

**Konteks.** Ada webhook, scheduler, chat, dan (mudah tergoda) endpoint "run" untuk debugging.

**Keputusan.** Trigger bisnis hanya masuk lewat `POST /webhook` (secret) atau chat/slash command.
Scheduler memanggil fungsi Python langsung, bukan HTTP. Tidak ada endpoint HTTP untuk menjalankan
agent.

**Konsekuensi.** Permukaan serangan kecil dan audit mudah (satu log trigger). Untuk debugging,
pakai `python -m hermes_bridge.smoke`, bukan endpoint.

**Ditolak.** `POST /run-agent` (pintu ketiga tanpa auth yang benar); scheduler memanggil `POST
/webhook` (memutar secret di mesin sendiri, dan log trigger jadi ganda).

---

## ADR-12 — Dokumen sebagai sumber tunggal (docs-first)

**Konteks.** Blueprint Rev 3 punya 30 agent, 9 ruangan, 13 trigger, 11 job, 20+ env var, 12 tabel.
Tanpa satu sumber, nama akan menyimpang dalam satu minggu (contoh nyata: `biz-1` vs spot yang ada,
`require` di proyek ESM, 45 vs 30 agent).

**Keputusan.** Satu topik = satu file pemilik (BLUEPRINT §3). Dokumen lain menautkan, tidak menyalin.
Setiap perubahan kode yang menyentuh nama role/tabel/env/endpoint wajib memperbarui file pemiliknya.

**Konsekuensi.** Sedikit disiplin ekstra per PR, tapi tidak ada lagi "dokumen bilang A, kode bilang B".
Reviewer bisa menolak PR yang mengubah nama tanpa memperbarui dokumen.

**Ditolak.** Satu dokumen raksasa (konflik merge terus-menerus, sulit dibaca); dokumen per-agent
(fragmentasi, cepat usang).
