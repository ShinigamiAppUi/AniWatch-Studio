# Hermes Office — W11: Dua role `Scraper` & `Resolver`

Nov 17, 2026 · @Shin · **Status: spesifikasi, belum ada kode.**
Audit dasar: repo `ShinigamiAppUi/AniWatch` commit `b47e9f3` (dibaca 17 Nov 2026).
Katalog agent: [AGENTS.md](AGENTS.md) · Handoff: [AGENT-HANDOFFS.md](AGENT-HANDOFFS.md) ·
Scheduler: [SCHEDULER.md](SCHEDULER.md) · Roadmap sebelumnya: [PLAN.md](PLAN.md) (W1–W10 selesai).

Dokumen ini satu-satunya sumber untuk W11. Kalau kode dan dokumen ini berbeda, dokumen ini yang
salah sampai diperbaiki di commit yang sama.

---

## 1. Kenapa W11 ada

`Scraper` sudah jadi satu baris di `src/types.ts` sejak W2, tetapi pekerjaannya tidak pernah
tersambung ke backend. Audit 17 Nov 2026 menemukan:

| Temuan | Bukti |
| --- | --- |
| 178 adapter ada di disk (70 anime, 48 manga, 60 novel) | `backend/internal/scraper/{anime,manga,novel}/*/adapter.go` |
| Tidak ada factory dari `sources.name` → adapter; tidak ada satu pun konstruktor dipanggil runtime | grep `map[string]AnimeSource` / `New*` = 0; `registry_loader.go` hanya YAML → DB; `docs/plan/STATUS.md:170` mengakui hal yang sama |
| Hasil scrape tidak pernah ditulis | `UpsertScrapedResolverSource` tanpa pemanggil; `ResolveScrape` selalu 503 |
| `Race` generik ada dan ber-test, tapi tak dipakai | `backend/internal/scraper/race.go` |
| Registry: 433 sumber, `active` 32 (semua anime), `dead` 15, `unverified` 386 | `docs/scraper/registry.yaml` |
| Manga/novel tidak pernah masuk DB: loader melewati status selain `active`/`dead` | `LoadFromFile` di `registry_loader.go` |
| Health check hanya di SQL: 3× gagal → `dead`, periksa tiap 6 jam | `IncrementEpisodeSourceFail`, `ListStaleEpisodeSourcesForHealthCheck` — nol pemanggil Go |
| Resolver host baru 2 dari ~104 | `internal/media/{pixeldrain,direct}.go` vs 102 baris seed `media_hosts` |
| `PageResolver` (halaman episode → kandidat) tidak ada di Go, hanya di dokumen/skill | D-64 menyebut dua registry; `internal/episode` tidak ada |
| Perubahan domain situs hanya `PATCH /v1/admin/sources/anime/:name/baseurl`, string mentah tanpa validasi | `internal/handler/sources_handler.go:136` |

Kesimpulan audit itulah dasar pembagian kerja: **sumber** (433 situs, adapter per situs, hasil =
baris konten) dan **host** (~104 host + halaman episode, hasil = URL putar berumur pendek) adalah
dua pekerjaan dengan bahan, verifikasi, dan tempo yang berbeda. Satu role yang mengerjakan keduanya
akan menahan episode baru di belakang antrean backfill ribuan baris.

**Koreksi terhadap permintaan awal:** "isi URL direct host ke DB" sebagian bertentangan dengan
D-64. Yang disimpan adalah `provider` + `source_page_url`; URL putar di-resolve ulang saat playback
(cache 5 menit) karena link host bertanda tangan cepat kedaluwarsa. W11 tidak menambah kolom
`direct_url` permanen.

---

## 2. Pembagian lapis (jangan dicampur)

Pekerjaan nyata ada di backend Go AniWatch: di situ ada adapter, DB, allowlist, dan probe. Role
kantor **tidak** mengikis situs dari laptop; mereka menjalankan, mengawasi, dan melaporkan lewat
endpoint admin.

```
AniWatch backend (Go, selalu jalan)          Hermes office (Python + kantor)
├─ scraper factory + runner  ──HTTP──▶  Scraper  (🕷️ biz-s1)  picu, laporkan, usulkan domain
├─ PageResolver + LinkResolver ─HTTP──▶  Resolver (🔗 biz-s10)  segarkan, laporkan host mati
└─ health job (6 jam)          ──HTTP──▶  /scrape /resolver /sources
```

Kalau kantor mati, backend tetap memanen dan memeriksa health sendiri. Kalau backend mati, role
melaporkan "tidak terjangkau", bukan angka palsu.

### 2.1 Empat istilah yang mudah tertukar

`Resolver`, `PageResolver`, `LinkResolver`, dan host `direct` sering dianggap satu hal karena
keempatnya berujung pada "URL putar". Mereka bukan sinonim: bedanya ada di bahan masuk, bahan
keluar, dan di lapis mana masing-masing berada.

| Istilah | Apa itu | Bahan masuk | Bahan keluar | Di mana |
| --- | --- | --- | --- | --- |
| **Resolver** | Nama lapis **dan** role kantor (🔗 `biz-s10`) — bukan satu fungsi dan bukan satu host | — | laporan host mati, antrean `need_direct` yang selesai | §5.1, §5.3 |
| **`PageResolver`** | Registry adapter **halaman episode**: `CanHandle(rawURL)`, `Candidates(pageURL)` | `source_page_url` sebuah halaman episode | daftar kandidat mentah (embed/iframe) — **belum** URL putar | `internal/pageresolve/` (§4.3) |
| **`LinkResolver`** | Registry adapter **host media** (~104 host, sejajar tabel `media_hosts`) | kandidat / URL host | URL putar + hasil probe (mime, `playable`) | `internal/media/` (§4.4) |
| **host `direct`** | **Satu adapter** di dalam `LinkResolver`, bukan lapis tersendiri | URL yang **sudah** berupa file langsung, dicek ke allowlist `MEDIA_DIRECT_HOSTS` | URL yang sama setelah probe; atau ditolak / `host_not_supported` | `internal/media/direct.go` |

Urutannya: `source_page_url` → **PageResolver** → kandidat → **LinkResolver** (salah satu
adapter-nya bisa `direct`) → URL putar. Dua jalan pintas yang sah: kalau `sumber` sudah punya
adapter, `PageResolver` dilewati karena adapter itulah yang mengekstrak embed; kalau URL-nya memang
sudah URL host langsung, `PageResolver` juga dilewati dan `LinkResolver` langsung memilih `direct`.

Yang **tidak** boleh disimpulkan dari tabel ini:

- "Resolver = host `direct`". `direct` hanya kasus paling sederhana (tanpa ekstraksi) dari ~104 host;
  pixeldrain, HLS, dan host embed tetap butuh adapter masing-masing.
- "PageResolver boleh dipakai untuk semua sumber". Ia hanya dipakai bila sumber **tidak** punya
  adapter (§4.3); satu halaman tidak boleh punya dua parser dengan hasil berbeda.
- "Resolver menyimpan URL putar". Tidak ada kolom `direct_url`. Yang disimpan `provider` +
  `source_page_url`; URL putar lahir ulang saat playback (cache 5 menit) dan berumur pendek (§1).
- "Host tanpa adapter = gagal". Barisnya tetap boleh disimpan; ia hanya dilewati plan dengan alasan
  `host_not_supported`, dan alasan itu wajib muncul di laporan Resolver, bukan hilang (§4.4).

---

## 3. Kontrak tulis: satu field satu penulis

| Field / keputusan | Penulis tunggal | Pembaca |
| --- | --- | --- |
| `episode_sources` baris `origin='scraper'` | runner backend | Resolver, Planner |
| `episode_sources.health` / `fail_count` | health job | Planner (`ListEpisodePlanSources`) |
| `episode_sources` baris `origin='manual'` | admin (m47) | semua — **tidak pernah** ditimpa (D-43) |
| `provider`, `source_page_url` | runner / admin | LinkResolver |
| URL putar | tidak disimpan; cache 5 menit di memori | playback |
| `sources.base_url` | **manusia lewat approval** (§8) | adapter, Resolver |
| `sources.is_active` | health job (otomatis, dengan laporan) | loader, race |
| Antrean backfill (`scraper_queue`) | runner meng-claim lease | role (baca saja) |

Handoff (AGENT-HANDOFFS.md §3):

| Handoff | Dari → ke | Isi |
| --- | --- | --- |
| `need_direct` | Scraper → Resolver | `content_type`, `target_id`, `source_id`, `page_url` |
| `direct_ready` | Resolver → Scraper | `target_id`, `provider`, `probe: {status, content_type, bytes}`, `expires_at` |
| `source_health_failed` | health job → Scraper | `source_id`, `fail_count`, `last_error` |
| `domain_candidate` | Scraper → manusia | `source_id`, `old_url`, `new_url`, `evidence[]` — **tidak menulis DB** |

Context key (DB-SCHEMA.md §11): `source:<content_type>:<source_id>`, `direct:<content_type>:<target_id>`.
Catatan ini tidak menyimpan status episode — itu milik backend.

---

## 4. Lapis A — backend AniWatch

### 4.1 `internal/scraper/factory.go` (baru)

- `Factory` memetakan `sources.name` → konstruktor adapter per domain:
  `Anime(name) (AnimeSource, error)`, `Manga(name)`, `Novel(name)`.
- Tabel registrasi **digenerate** dari `registry.yaml` + pemindaian disk, bukan ditulis tangan:

  ```bash
  ./scripts/gen-adapter-registry.sh   # docs/scraper/registry.yaml → internal/scraper/adapters_gen.go
  ```

  Alasannya: 178 adapter dengan 178 import tangan akan selalu tertinggal satu baris tiap kali
  adapter baru mendarat, dan `check-scraper-coverage.sh` tidak bisa membedakan "lupa didaftarkan"
  dari "memang belum ada".
- Nama tidak dikenal → `ErrUnknownAdapter` (sentinel), bukan `nil, nil`. Sumber `dead` / tidak
  `active` → `ErrSourceInactive`, sehingga runner tidak perlu tahu soal status di DB.
- `check-scraper-coverage.sh` ditambah satu pemeriksaan: setiap adapter di disk muncul di
  `adapters_gen.go`, dan sebaliknya. Ini yang menutup celah "108 adapter manga/novel tidak pernah
  masuk DB".

### 4.2 `internal/scraper/runner.go` (baru)

- `RunAnime(ctx, episodeID)`, `RunManga(ctx, chapterID)`, `RunNovel(ctx, chapterID)`:
  baca baris sumber aktif dari DB → `Factory` → `Race` (timeout bersama `DefaultTimeout`) → tulis
  hasil.
- Menulis lewat query yang sudah ada: `UpsertScrapedResolverSource` untuk baris `origin='scraper'`,
  `racelog.go` untuk `scraper_race_logs`, `SetEpisodeSourceHealth` untuk hasil yang diperiksa.
  Idempotensi: unique index yang sudah ada; `ON CONFLICT DO NOTHING` berarti baris manual menang.
- Kegagalan per sumber dicatat sebagai nilai (`last_error`), bukan `panic` dan bukan ditelan.
- `MediaResolver.ResolveScrape` di `internal/domain/stream/media_resolver.go` diganti: memanggil
  runner dengan timeout, dan tetap mengembalikan error yang bisa dibaca kalau `SCRAPE_ENABLED=false`.

### 4.3 `internal/pageresolve/` (baru, D-64)

Lapis pertama dari dua lapis resolve (§2.1): halaman → kandidat, tanpa menyentuh host.

- `PageResolver`: `Slug()`, `DisplayName()`, `CanHandle(rawURL)`, `Candidates(ctx, pageURL) []Candidate`
  — halaman episode → daftar kandidat (embed/iframe) **tanpa** resolve host. Registry-nya sejajar
  dengan `media.Registry` (LinkResolver), bukan di dalamnya.
- Batas anti-duplikasi: adapter anime yang sudah mengekstrak embed di `FetchEpisode` tetap memakai
  parser-nya sendiri. `PageResolver` hanya dipakai lapis `resolver` untuk sumber yang **tidak**
  punya adapter. Satu halaman tidak boleh punya dua parser yang berbeda hasilnya.
- Dipakai `Scanner`/`Runner` saat lapis `scrape` tidak tersedia tetapi `source_page_url` diketahui.

### 4.4 Resolver host (`internal/media`)

Lapis kedua (§2.1): kandidat → URL putar. `direct` adalah salah satu adapter di sini, bukan nama
lapis dan bukan nama role.

- Registry sudah benar (`LinkResolver`, `CanHandle` tanpa network, `ForURL` deterministik) — **jangan
  dirombak**. Yang ditambah hanya adapter, satu per gelombang, tiap adapter wajib: fixture respons
  + tanggal ambil + dossier `docs/media-url/<host>.md` + test offline.
- Gelombang 1 (3 host): satu host file populer, satu HLS, satu embed halaman yang sudah tercatat di
  `media_hosts`. Gelombang 2+ hanya setelah gelombang 1 hijau.
- MIME dan playability dari probe (`GET Range: bytes=0-1`, terima 200/206), bukan dari tebakan
  nama berkas. Host tanpa adapter tetap boleh disimpan, tetapi dilewati plan (`host_not_supported`)
  — status itu harus terlihat di laporan Resolver, bukan hilang.

### 4.5 Antrean backfill — migrasi `000020_scraper_queue.up.sql` (baru)

Satu baris per pekerjaan, supaya restart tidak mengulang dari nol:

```
id, content_type, source_id, target_id, state ('queued'|'claimed'|'done'|'gave_up'),
attempts, lease_until, next_try_at, last_error, created_at, updated_at
```

- Claim: `UPDATE ... SET state='claimed', lease_until=NOW()+interval '10 minutes'
  WHERE id = (SELECT id FROM scraper_queue WHERE state='queued' AND next_try_at <= NOW()
  ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING *`.
- Backoff pengulangan: 1 mnt → 5 → 15 → 60, maksimal `SCRAPER_MAX_ATTEMPTS=5`, lalu `gave_up`
  dengan `last_error` — pola yang sama dengan surat selamat datang yang menyerah (Rev 4.3/4.4),
  supaya "gagal berhenti" punya arti yang konsisten di seluruh kantor.
- **Rate limit per host** (token bucket di memori, kunci = host `base_url`) dipakai **bersama** oleh
  runner dan Resolver. Menambah worker tidak menambah tekanan ke satu situs.

### 4.6 Health job (bukan role)

- 6 jam sekali: `ListStaleEpisodeSourcesForHealthCheck` → probe → `SetEpisodeSourceHealth` atau
  `IncrementEpisodeSourceFail` (3× → `dead`). Query sudah ada; W11 hanya memanggilnya dari
  `internal/scheduler`.
- Tingkat sumber: `anime_sources`/`manga_sources`/`novel_sources` ditambah `consecutive_fail`
  (migrasi yang sama). 3× gagal berurutan → `is_active=false` + laporan ke Scraper. Tidak ada
  penulisan `base_url` di sini (§8).
- Report ditulis ke `scraper_logs` (migrasi `000018` sudah ada).

### 4.7 Endpoint admin baru

Semua `adminOnly(...)` dan tercatat di audit log yang sudah ada (`GET /v1/admin/audit`):

| Endpoint | Guna |
| --- | --- |
| `POST /v1/admin/scrape/run` | jalankan runner untuk satu target / satu sumber (`dry_run` untuk uji parser) |
| `POST /v1/admin/scrape/backfill` | isi `scraper_queue` dari sumber aktif (batas `SCRAPE_MAX_SITES`) |
| `GET /v1/admin/scrape/queue` | ringkasan antrean: `queued/claimed/done/gave_up` per domain |
| `POST /v1/admin/media/resolve` | dry-run resolver (m48 yang belum ada): provider, mime, `playable`, `warnings[]`, tidak menulis DB |
| `GET /v1/admin/sources/health` | `consecutive_fail`, `last_error`, `checked_at` per sumber |

`PATCH /admin/sources/anime/:name/baseurl` diperketat di §8.

---

## 5. Lapis B — kantor Hermes

### 5.1 `Resolver` (role baru, ke-46)

- `src/types.ts`: `Resolver: { color: '#22d3ee', emoji: '🔗', desk: 'biz-s10', room: 'server-room' }`
  — key persis `Resolver`, tidak bentrok dengan `Security`/`Reviewer` (AGENTS.md §1).
- `src/rooms.ts` + ROOMS.md §5.2: spot `biz-s10` di `x: 53.5, y: 76.0`, `facing: 'up'`, `spriteFacing: 'rear-left'`, `zIndex: 72` — di luar baris `srv-1..srv-6` (x 35–50, y 47–58) dan enam rak `srv-rack-*`. Koordinat ini wajib dicek di layar sebelum ditandai selesai; tabrakan dengan meja lain tidak akan memunculkan error, hanya karakter yang duduk menumpuk. Header ROOMS jadi `biz-s1..s10`; jumlah role Server Room 9 → 10.
- Total agent 45 → 46 (AGENTS.md, ROOMS.md, BLUEPRINT.md ikut diperbarui di commit yang sama).

### 5.2 `hermes_agents/scraper.py` (baru)

- `backfill(limit)`, `run_target(episode_id)`, `sources_health()`, `propose_domain(source_id, new_url)`.
- Semua lewat HTTP admin (`ANIWATCH_API_URL` + `ANIWATCH_ADMIN_TOKEN`). Tanpa token: kembalikan
  `{'ok': False, 'reason': 'ANIWATCH_ADMIN_TOKEN belum diisi'}` — bukan daftar kosong yang terlihat
  seperti "semua sehat".
- `propose_domain` **tidak** memanggil PATCH. Ia mengirim approval card berisi bukti:
  rantai redirect, sertifikat, penanda kanonik (judul/slug yang sama). Tanpa approval, tidak ada
  tulisan.

### 5.3 `hermes_agents/resolver.py` (baru)

- `refresh_due(limit)` — ambil `need_direct` yang menua, panggil `POST /admin/media/resolve`,
  kembalikan `direct_ready` bila probe lolos.
- `unresolved_hosts()` — host di `media_hosts` tanpa adapter, diurutkan dari frekuensi pemakaian;
  inilah daftar kerja gelombang berikutnya, bukan tebakan.
- `health_report()` — baris `dead`/`degraded` + `gave_up` queue, satu ringkasan untuk `/resolver`.

### 5.4 Job (`webhook_server/jobs.py` + `scheduler.py`, 12 → 15)

| id | Jadwal | Fungsi | Timeout |
| --- | --- | --- | --- |
| `source_health` | tiap 30 menit | `scraper.sources_health()` → `source_health_failed` | 120 dtk |
| `scraper_backfill` | tiap jam | `scraper.backfill(SCRAPER_BACKFILL_BATCH)` | 300 dtk |
| `resolver_refresh` | tiap 6 jam | `resolver.refresh_due(...)` | 600 dtk |

Ketiganya job internal (tidak lewat Orchestrator), idempoten, dan tidak melempar (SCHEDULER.md §1).

### 5.5 Command chat (API-REFERENCE.md §6)

- `/scrape [source|episode]` — antrean + kegagalan terakhir, maksimal 6 baris.
- `/resolver` — host mati/degraded, host tanpa adapter, `gave_up`.
- `/sources` — jumlah `active`/`dead`/`unverified` per domain, dengan angka dari endpoint, bukan
  dari ingatan.

---

## 6. Konfigurasi baru (ENV-VARS.md)

| Var | Sisi | Default | Guna |
| --- | --- | --- | --- |
| `ANIWATCH_API_URL` | kantor | kosong | basis endpoint admin |
| `ANIWATCH_ADMIN_TOKEN` | kantor | kosong | token admin; tanpa ini role melapor "belum dikonfigurasi" |
| `SCRAPER_BACKFILL_BATCH` | kantor | `50` | item per jam |
| `SCRAPER_MAX_ATTEMPTS` | backend | `5` | sebelum `gave_up` |
| `SCRAPER_LEASE_MINUTES` | backend | `10` | lease claim antrean |
| `SCRAPE_MAX_SITES` | backend | sudah ada | batas sumber per siklus |
| `MEDIA_DIRECT_HOSTS` | backend | sudah ada | allowlist `direct` (D-64) |

---

## 7. Verifikasi (DoD)

Backend:

```bash
cd backend && go build ./... && go vet ./...
cd backend && go test ./internal/scraper/... ./internal/media/... ./internal/pageresolve/...
./scripts/gen-adapter-registry.sh && ./scripts/check-scraper-coverage.sh
```

- Test parser tetap offline (fixture), bukan memanggil situs nyata.
- `POST /admin/media/resolve` diuji: URL valid, `/l/` ditolak, 404, non-video, host tak dikenal
  (422), redirect ke IP privat ditolak.
- Health job diuji dengan `episode_sources` palsu: 2× gagal tetap `degraded`, ke-3 → `dead`, sukses
  mereset `fail_count`.

Kantor (PLAN.md "Definition of done"):

```bash
python -m compileall hermes_bridge hermes_agents webhook_server
python -m hermes_agents.selfcheck
npx tsc --noEmit && npx vitest run
```

Selfcheck baru memakai stub HTTP (`ThreadingHTTPServer` lokal, pola W8) — tidak ada jaringan nyata,
dan kasus "token kosong" diuji supaya role tidak pernah melaporkan sehat tanpa data.

---

## 8. Perubahan domain situs — usul, bukan tulis

`PATCH /v1/admin/sources/anime/:name/baseurl` sekarang menerima string apa pun. Sebelum W11 boleh
disebut "auto-heal domain", endpoint itu harus:

1. parse URL, hanya `https`, tanpa IP literal / host privat (pakai klien anti-SSRF `internal/media`);
2. ikuti maksimal 3 redirect dan catat rantainya;
3. probe halaman daftar + satu halaman detail; cocokkan penanda kanonik (judul situs, pola slug,
   atau elemen yang sama dengan fixture terakhir);
4. hanya setelah itu tulis — dan **tetap** lewat approval manusia (`approval.py`, kartu ✋) karena
   domain baru adalah keputusan identitas sumber, bukan keputusan mesin.

Situs yang mati tidak diganti URL karangan (D-67 larangan anti-fabrikasi): status `dead` +
`status_note` adalah hasil yang sah.

---

## 9. Urutan kerja (satu fase satu commit)

| Fase | Isi | Selesai bila |
| --- | --- | --- |
| **W11a** | factory + `adapters_gen.go` + runner + `ResolveScrape` | satu episode nyata punya baris `origin='scraper'` dan race log; `check-scraper-coverage.sh` lulus |
| **W11b** | health job + antrean `000020` + rate limit per host + endpoint admin §4.7 | sumber mati jadi `is_active=false` tanpa deploy; `gave_up` terlihat |
| **W11c** | `PageResolver` + gelombang 1 resolver host (3 host) | halaman episode tanpa adapter menghasilkan `direct_ready` yang lolos probe |
| **W11d** | role `Resolver` + `scraper.py`/`resolver.py` + 3 job + `/scrape` `/resolver` `/sources` | karakter `Resolver` muncul di `biz-s10` dan ketiga command menjawab angka nyata |

W11a dan W11b boleh jalan paralel setelah factory mendarat; W11d menunggu endpoint §4.7 ada,
karena role tanpa endpoint hanya akan mengarang laporan.

---

## 10. Yang eksplisit TIDAK dikerjakan

- Menyalakan 386 sumber `unverified` secara massal; status naik per sumber setelah fixture + dossier.
- Menaikkan manga/novel ke `active` tanpa verifikasi hanya agar loader memuatnya.
- Menyimpan direct URL permanen di DB (bertentangan dengan D-64).
- Proxy byte video di backend (bandwidth; ADR terpisah).
- Auto-accept domain baru, atau menulis `base_url` tanpa approval.
- Scraping situs berbayar / melanggar ToS — status `blocked_tos`, bukan adapter.
- Mencampur `PageResolver` ke dalam `internal/media` atau ke adapter yang sudah punya parser.

---

## 11. Risiko

| Risiko | Dampak | Mitigasi |
| --- | --- | --- |
| 178 adapter tanpa test | regresi senyap saat factory disambungkan | factory hanya memuat adapter yang punya fixture + test; sisanya `unverified` dan tidak dipanggil |
| Backfill agresif | situs memblokir IP/server | token bucket per host, batch kecil, `SCRAPE_MAX_SITES` |
| Link host cepat kedaluwarsa | playback 502 sesudah beberapa jam | resolve malas + cache 5 menit; `expires_at` di `direct_ready` |
| Health job mematikan sumber sehat karena satu 503 | konten hilang dari race | ambang 3× berurutan + laporan + `is_active` bisa dinyalakan lagi lewat admin |
| Role kantor melapor "sehat" tanpa backend | keputusan salah | tanpa token/endpoint, jawabannya `ok: false` + alasan |
