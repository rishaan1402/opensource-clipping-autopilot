#!/bin/bash

echo "🧹 Memulai proses pembersihan file sementara (cleanup)..."

# Memastikan direktori uploads dan outputs ada
mkdir -p uploads outputs

# 1. Membersihkan folder uploads
echo "🗑️  Menghapus semua file video mentah di dalam uploads/..."
find uploads -type f -delete

# 2. Membersihkan file sementara di dalam folder outputs/
echo "🗑️  Menghapus video sumber (raw) dan file audio sementara di dalam outputs/..."
# Ini akan menyisakan final klip (.mp4 hasil render) dan histori JSON
find outputs -type f -name "video_asli.mp4" -delete
find outputs -type f -name "*_audio.wav" -delete
find outputs -type f -name "*.json3" -delete

# 3. Membersihkan Cache Python
echo "🗑️  Menghapus file cache Python (__pycache__)..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null
find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null

# 4. Membersihkan node_modules frontend
echo "🗑️  Menghapus node_modules frontend..."
# Docker menggunakan volume tersendiri untuk node_modules di dalam container, jadi menghapusnya di lokal host aman.
rm -rf web/dashboard/node_modules
rm -rf web/dashboard/dist

# 5. Membersihkan .cache & .local (WARNING)
# Hati-hati: Folder .cache menyimpan model AI (HuggingFace/Whisper) berukuran Gigabytes!
# Jika dihapus, pipeline akan mendownload ulang model AI dari awal. Buka komentar di bawah JIKA Anda benar-benar ingin menghapusnya.
# echo "🗑️  Menghapus .cache dan .local..."
# rm -rf .cache .local

echo "✅ Pembersihan selesai! Ruang penyimpanan telah dibebaskan."
