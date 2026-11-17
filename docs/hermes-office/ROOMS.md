# Hermes Office — Room Layout

Nov 16, 2026 · @Shin · Mengikat [AGENTS.md](AGENTS.md) (kolom `room`/`desk`) dan `src/rooms.ts`

Kantor punya **9 ruangan di 2 lantai**. Lantai 1 adalah 5 ruangan base yang tidak diubah. Lantai 2
menambah 4 ruangan dengan **memakai ulang pixel art yang sama** — tidak ada artwork baru, hanya
`background` yang menunjuk file yang sudah ada dan daftar spot baru.

---

## 1. Daftar ruangan

| # | Ruangan | `RoomId` | Lantai | Art (reuse) | Spot bisnis | Isi |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Main Office | `main-office` | 1 | `main-office.png` | `biz-m1..m3` | dev desks base (10) + Community |
| 2 | Corridor | `corridor` | 1 | `corridor.png` | — | hub navigasi, pintu depan, lift |
| 3 | Meeting Room | `meeting-room` | 1 | `meeting-room.png` | — (ad-hoc) | approval, handoff, rapat |
| 4 | Server Room | `server-room` | 1 | `server-room.png` | `biz-s1..s10` | MCP base (6) + Core Ops (10) |
| 5 | Lunch Room | `lunch-room` | 1 | `lunch-room.png` | — | istirahat, agent idle lama |
| 6 | Business Suite | `business-suite` | 2 | **`meeting-room.png`** | `biz-b1..b6` | Orchestrator, Sales, Marketing, Ops |
| 7 | Creative Studio | `creative-studio` | 2 | **`main-office.png`** | `biz-c1..c10` | Growth + Premium pipeline |
| 8 | Finance & Legal | `finance-legal` | 2 | **`server-room.png`** | `biz-f1..f4` | Revenue, Payment, DMCA, SecOps |
| 9 | Exec Floor | `exec-floor` | 2 | **`meeting-room.png`** | `exec-1..exec-2` | CEO (boss) + tamu |

Spot bisnis dipakai **hanya** oleh agent bisnis. Spot base (`spot-*`, `srv-*`, `meet-*`,
`lounge-*`) tetap milik dev, MCP, dan rapat — tidak ada satu pun yang dipakai ulang. Ini yang
membuat 30 agent bisnis tidak pernah berebut kursi dengan 15 specialist dev.

---

## 2. Denah

```
                          LANTAI 2
   ┌───────────────────┐   ┌────────────────────┐   ┌──────────────────┐
   │  Business Suite   │   │  Creative Studio   │   │  Finance & Legal │
   │  4+2 spot         │   │  10 spot           │   │  4 spot          │
   │  Orchestrator     │   │  Growth + Premium  │   │  Revenue/Payment │
   │  Sales/Marketing  │   │  pipeline          │   │  DMCA/SecOps     │
   │  Ops              │   │                    │   │                  │
   └─────────┬─────────┘   └──────────┬─────────┘   └────────┬─────────┘
             │                        │                      │
             └────────────┬───────────┴──────────┬───────────┘
                          │        LIFT          │
   ═══════════════════════╪══════════════════════╪═══════════════════════
                          │       LANTAI 1       │
                   ┌──────┴──────┐               │
                   │  Corridor   │───────────────┘
                   │  (hub)      │
                   └──┬───┬───┬──┘
        ┌─────────────┘   │   └──────────────┐
        ▼                 ▼                  ▼
 ┌─────────────┐  ┌─────────────┐   ┌──────────────┐   ┌────────────┐
 │ Main Office │  │Meeting Room │   │ Server Room  │   │ Lunch Room │
 │ dev + Comm. │  │ ad-hoc      │   │ MCP + Core   │   │ istirahat  │
 └─────────────┘  └─────────────┘   └──────────────┘   └────────────┘
```

Aturan navigasi (sama seperti base): **tidak ada perpindahan langsung antar ruangan.** Rute selalu
`pintu sendiri → koridor → pintu tujuan`. Untuk lantai 2, koridor punya satu titik **lift**; naik
lift = satu transisi ruangan, bukan animasi tangga.

---

## 3. Alur agent per ruangan

| Kejadian | Dari | Ke | Catatan |
| --- | --- | --- | --- |
| Agent bisnis spawn | pintu depan koridor | kursinya | lewat koridor, lift kalau lantai 2 |
| Butuh approval | kursi | Meeting Room | kursi asli tetap di-reserve (`visitSpotId`) |
| Selesai rapat | Meeting Room | kursi | kembali, lalu keluar kalau task selesai |
| Task selesai | kursi | pintu depan koridor | animasi 👍 dulu |
| Idle > 15 menit | kursi | Lunch Room | hanya kalau tidak memegang task |
| Orchestrator delegasi | Business Suite | tetap | Orchestrator tidak berpindah, hanya bicara |

Engine yang menangani ini tidak diubah: `roomRules.ts` (siapa di mana), `roomTransfer.ts` (jalan
antar ruangan), `walk.ts` (animasi). Yang ditambah hanya data ruangan dan satu aturan di
`roomRules.ts`: **role bisnis → `assignedRoom` dari config**, bukan dari aturan dev.

---

## 4. Perubahan `src/rooms.ts`

Tiga tambahan, semuanya **aditif** (tidak mengubah tipe yang sudah ada):

```ts
// 1. RoomId — 4 id baru
export type RoomId =
  | 'main-office' | 'corridor' | 'meeting-room' | 'server-room' | 'lunch-room'
  | 'business-suite' | 'creative-studio' | 'finance-legal' | 'exec-floor'

// 2. Room — dua field opsional
export interface Room {
  // ... field base tidak berubah
  floor?: 1 | 2                    // default 1; dipakai floor plan di pojok
  artReuse?: RoomId                // ruangan yang art-nya dipinjam (dokumentasi)
}

// 3. RoomLandmark — satu kind baru untuk lift
export interface RoomLandmark {
  id: string
  kind: 'front-door' | 'decor-door' | 'lift'
  label: string
  x: number
  y: number
}
```

`background.day`/`background.night` untuk lantai 2 menunjuk file art yang sama dengan sumbernya
(mis. `business-suite` → `meeting-room` day/night). Karena geometri ruangan base identik
(1508×1126, atau 4800×3584 untuk art 4×), posisi pintu yang sudah diukur **bisa dipakai ulang**
apa adanya; spot baru cukup diletakkan di area lantai yang sudah terukur.

---

## 5. Desk slot map

Semua koordinat adalah persen (0–100) dari gambar ruangan, dan **persis nilai di `src/rooms.ts`**
(`agentSpots`). Semua sudah dicek berada di dalam `walkableArea` ruangannya oleh `tests/rooms.test.ts`;
geser dengan `/?helper&room=<id>` kalau perlu, lalu perbarui tabel ini dan kode sekaligus.

### 5.1 Main Office — `biz-m1..m3`

Deretan meja paling kanan-belakang, di luar 10 `spot-*` dev (dan tidak pernah dipakai hire dev:
`pickSpot` melewati semua `biz-*`).

| Desk | Role | x | y | facing | zIndex |
| --- | --- | --- | --- | --- | --- |
| `biz-m1` | Support | 74.5 | 63.5 | down | 62 |
| `biz-m2` | Moderator | 79.0 | 60.0 | down | 60 |
| `biz-m3` | UserReportAgent | 83.0 | 57.0 | down | 58 |

### 5.2 Server Room — `biz-s1..s10`

Sisi kanan lantai (berlian), di luar 6 `srv-*` MCP; dijangkau dari junction `W-srv-biz` yang
tersambung ke `W-srv-in` (dekat pintu).

| Desk | Role | x | y |
| --- | --- | --- |
| `biz-s1` | Scraper | 68.0 | 60.0 |
| `biz-s2` | Metadata | 72.5 | 63.0 |
| `biz-s3` | Encoder | 77.0 | 66.0 |
| `biz-s4` | Subtitle | 66.0 | 68.0 |
| `biz-s5` | TranslationAgent | 70.5 | 71.0 |
| `biz-s6` | QualityChecker | 75.0 | 74.0 |
| `biz-s7` | EpisodeScheduler | 62.0 | 74.0 |
| `biz-s8` | Notifier | 66.5 | 77.0 |
| `biz-s9` | CacheWarmer | 58.0 | 80.0 |
| `biz-s10` | Resolver | 53.5 | 76.0 |

Semua `facing: 'up'`, `spriteFacing: 'rear-left'`, `zIndex` 62–72.

### 5.3 Business Suite — `biz-b1..b6`

Meja rapat panjang, art `meeting-room.png`. Empat dipakai, dua cadangan untuk agent generic baru.

| Desk | Role | x | y | facing |
| --- | --- | --- | --- | --- |
| `biz-b1` | Orchestrator | 33.3 | 64.4 | down |
| `biz-b2` | Sales | 38.6 | 60.8 | down |
| `biz-b3` | Marketing | 43.9 | 57.1 | down |
| `biz-b4` | Ops | 49.2 | 53.5 | down |
| `biz-b5` | *(cadangan)* | 46.5 | 74.1 | up |
| `biz-b6` | *(cadangan)* | 52.0 | 70.3 | up |

### 5.4 Creative Studio — `biz-c1..c10`

Art `main-office.png`; 10 kursi = tepat 10 agent Growth + Premium.

| Desk | Role | x | y |
| --- | --- | --- | --- |
| `biz-c1` | Analytics | 25.8 | 71.0 |
| `biz-c2` | SEO | 37.9 | 68.2 |
| `biz-c3` | SocialMedia | 26.9 | 59.2 |
| `biz-c4` | Recommendation | 38.5 | 55.2 |
| `biz-c5` | Retention | 48.9 | 52.9 |
| `biz-c6` | DesignAgent | 38.8 | 43.6 |
| `biz-c7` | QAAgent | 52.7 | 78.8 |
| `biz-c8` | PricingAgent | 65.9 | 75.8 |
| `biz-c9` | PreviewAgent | 55.2 | 66.8 |
| `biz-c10` | Publisher | 68.7 | 66.2 |

### 5.5 Finance & Legal — `biz-f1..f4`

Art `server-room.png`; empat meja berkas.

| Desk | Role | x | y |
| --- | --- | --- | --- |
| `biz-f1` | RevenueTracker | 30.4 | 61.0 |
| `biz-f2` | PaymentAgent | 35.3 | 57.7 |
| `biz-f3` | DMCA | 40.1 | 54.3 |
| `biz-f4` | SecOps | 45.0 | 50.9 |

### 5.6 Exec Floor — `exec-1..exec-2`

Art `meeting-room.png`. Dua meja kerja: `exec-1` (33.3, 64.4, down) dan `exec-2` (38.6, 60.8, down).
Karakter `boss` tetap memakai `spot-1` di Main Office; ruangan ini untuk exec/agent bisnis yang
didaftarkan di `BUSINESS_AGENT_CONFIGS` atau untuk sesi review.

---

## 6. Kapasitas & overflow

| Ruangan | Spot bisnis | Agent bisnis | Sisa |
| --- | --- | --- | --- |
| Main Office | 3 | 3 (Support, Moderator, UserReportAgent) | 0 |
| Server Room | 10 | 10 Core Ops | 0 |
| Business Suite | 6 | 4 | 2 |
| Creative Studio | 10 | 10 | 0 |
| Finance & Legal | 4 | 4 | 0 |
| **Total** | **33** | **31** | **2** |

Kalau sisa spot habis dan ada agent baru: **jangan** menumpuk di satu meja. Aturan base tetap
berlaku — agent tanpa spot menunggu di lobby (`AgentState: 'waiting'`), dan itu terlihat di kantor
(tanda bahwa kapasitas ruangan perlu ditambah). Menambah spot = tambah entri di `agentSpots`, bukan
menambah artwork.

---

## 7. Checklist menambah ruangan

- [ ] `RoomId` di `src/rooms.ts`
- [ ] entri `ROOMS` dengan `background` (boleh menunjuk art yang sudah ada) + `floor` + `artReuse`
- [ ] `connections` dua arah ke `corridor` (satu pintu), posisi pintu diukur ulang atau dipinjam
- [ ] `entryPoint` + `walkableArea` (poligon lantai)
- [ ] `agentSpots` dengan id unik berprefix ruangan
- [ ] `roomAccess.ts`: ruangan baru dianggap ada kalau art-nya ada (tanpa flag `?rooms=all`)
- [ ] kalau lantai 2: titik `lift` di koridor + `connections` dari lift ke ruangan
- [ ] `tests/rooms.test.ts`: id unik, semua `connections.toRoom` ada, semua spot di dalam 0–100
- [ ] `npm run check-assets`: file background benar-benar ada
- [ ] setel posisi lewat `/?helper&room=business-suite`
