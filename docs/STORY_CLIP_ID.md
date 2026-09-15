# Story Clip Mode (--story-mode)

[English](./STORY_CLIP.md)

Fitur **Story Clip** adalah pipeline *multi-source narrative assembly* yang dirancang khusus untuk mengerjakan *campaign* (seperti *brand brief* Shopee, dll). Fitur ini memungkinkan Anda untuk mengambil potongan adegan (scene) spesifik dari berbagai sumber video (YouTube, TikTok, Instagram, Local, Google Drive) dan menggabungkannya menjadi sebuah cerita yang utuh secara otomatis berdasarkan spesifikasi waktu.

## Keunggulan
1. **Multi-Source**: Dapat mengambil potongan detik ke-sekian dari TikTok A, detik ke-sekian dari TikTok B, lalu menggabungkannya secara *seamless*.
2. **Otomatis Normalisasi**: Tidak peduli apakah video aslinya beda resolusi atau beda FPS, engine akan me-normalisasinya sehingga saat digabung (concat) tidak akan ada *glitch*.
3. **Pemisahan Hook dan Highlight**: Setiap klip yang didefinisikan akan menghasilkan 2 output video secara terpisah:
   - `hook_N.mp4`: Video teaser/hook untuk tarikan awal penonton.
   - `highlight_N.mp4`: Video isi cerita/highlight utama.
4. **Auto-Transkripsi Transparan (Whisper)**: Saat mendownload semua *source*, fitur ini akan otomatis melakukan transkripsi menggunakan Faster-Whisper dan menyimpannya di folder cache (`outputs/story_cache/*_transcript.json`). Ini sangat berguna jika Anda ingin membaca teks asli videonya untuk merancang *scene* atau *hook*.
5. **Clean Output**: Secara default, mode ini di-set menghasilkan video yang "bersih" (kosongan: tanpa subtitle bawaan, tanpa text overlay tambahan di hook) agar Anda bebas menumpuk text/effects di *software editing* lain.

## Cara Kerja (Pipeline)
1. **Load Sources**: Membaca daftar sumber video dari file `sources.json`.
2. **Download & Cache**: Mengunduh semua source dari platform (TikTok/IG/GDrive) dan menyimpannya di `outputs/story_cache/`. Sistem cerdas dan bersifat *idempotent* (file yang sudah di-download tidak akan di-download ulang).
3. **Transkripsi**: Mentranskrip audio setiap video sumber menggunakan Faster-Whisper.
4. **Load Recipe**: Membaca instruksi potongan adegan (skenario) dari `story_recipe.json`.
5. **Assembly**: Memotong setiap adegan menggunakan FFmpeg (`trim_scene`), me-normalisasi FPS/Resolusi, dan menggabungkannya tanpa *re-encoding* penuh (mempertahankan kualitas).
6. **Manifest**: Menyimpan laporan akhir di `outputs/story_manifest.json` beserta rangkuman status per-klip.

## Cara Menjalankan

Buka terminal di root direktori proyek, lalu jalankan perintah berikut:

```bash
python main.py --story-mode \
  --story-recipe story_recipe.json \
  --sources-json sources.json
```

**Opsi CLI Tambahan:**
- `--skip-download`: Mem-bypass proses pengecekan koneksi & download jika Anda yakin semua video mentahan sudah tersedia di folder `outputs/story_cache/`. Hal ini sangat mempercepat proses *assembly* saat melakukan iterasi waktu potong.
- `--story-output-dir outputs/shopee_campaign`: Gunakan ini jika Anda ingin menyimpan hasil akhir (klip MP4) ke folder yang spesifik (bukan default `outputs/story_clips/`).
- `--ratio 1:1` atau `--ratio 16:9`: Opsional jika Anda ingin memaksa rasio render secara global meskipun `story_recipe.json` telah memberikan default rasio `9:16`.

## Format `sources.json`

File ini bertugas untuk meregistrasikan semua tautan mentahan yang akan dipakai. 
- Wajib memiliki `id`, `name`, `url`, dan `platform` (mendukung `youtube`, `tiktok`, `instagram`, `gdrive`, atau `local`).

**Contoh:**
```json
{
  "$schema": "sources_v1",
  "sources": [
    {
      "id": "velia_2",
      "name": "Velia Video 2",
      "url": "https://www.tiktok.com/@veliachristyy/video/761675...",
      "platform": "tiktok"
    }
  ]
}
```

## Format `story_recipe.json`

File ini bertindak sebagai skenario cerita/sutradara digital Anda.
- Di dalam array `clips`, Anda mendefinisikan `clip_id`, `title`, dan bagian utama: `hook` serta `highlight`.
- Di dalam sub-objek `hook` / `highlight`, Anda menyusun urutan scene (adegan). Field `start` dan `end` (dalam satuan **detik** format desimal) menentukan secara absolut potongan waktu yang akan diambil dari `source_id` terkait.

**Contoh:**
```json
{
  "$schema": "story_recipe_v1",
  "project_name": "Shopee Fast Delivery",
  "default_settings": {
    "ratio": "9:16"
  },
  "clips": [
    {
      "clip_id": 1,
      "title": "Kecepatan Pengiriman",
      "hook": {
        "scenes": [
          {
            "source_id": "velia_2",
            "start": 0.0,
            "end": 10.0,
            "label": "Kurir mengantar paket"
          }
        ]
      },
      "highlight": {
        "scenes": [
          {
            "source_id": "donny_2",
            "start": 3.0,
            "end": 9.0,
            "label": "Donny beli jam 4 pagi"
          }
        ],
        "transition": "cut"
      }
    }
  ]
}
```

## Tips Alur Kerja (Workflow)
1. **Iterasi Waktu yang Cepat**: Karena semua *source* di-cache secara permanen, jika hasil klip terasa kurang pas timing-nya (misalnya kepanjangan 1 detik), Anda cukup mengubah angka `start` atau `end` di `story_recipe.json` lalu *run* ulang. Proses ini sangat efisien karena tidak ada *download* ulang.
2. **Gunakan Label**: Selalu gunakan atribut `label` pada setiap item `scene` di dalam JSON Anda. Ini memudahkan pelacakan konteks cerita tanpa harus memutar video mentahnya berulang kali.
