# YouTube Tracker

**Local YouTube Playlist Snapshot Tracker** for the OpenSource Clipping workflow.

Track which YouTube videos you've already used for clipping — across playlists, channels, and manual picks. All data stays local in a SQLite database.

## 🚀 Quick Start

```bash
# From the repo root:
python youtube_tracker/server.py
```

Open **http://127.0.0.1:8765** in your browser.

### Prerequisites

- Python 3.10+
- `yt-dlp` installed (already in project requirements)

```bash
pip install yt-dlp
```

## 📋 Features

### Add Playlist
1. Go to the Dashboard
2. Paste a YouTube playlist URL
3. Click **Add Playlist**
4. The tracker fetches metadata for the playlist and every video in it
5. All data is saved locally — no further YouTube calls

### Add Manual Video
1. Switch to the **+ Manual Video** tab on the Dashboard
2. Paste a YouTube video URL
3. Click **Add Video**
4. The video is fetched and added under the **Manual Videos** source

### Refresh / Pull Again
- Each source has a **🔄 Pull Again** button
- Clicking it re-fetches the playlist from YouTube
- **New videos** are added to the database
- **Missing videos** are marked (not deleted)
- **Existing video statuses** are preserved
- A pull summary shows what changed

### Mark Video Status
Each video has a global status:
- **unused** — not yet processed
- **candidate** — marked for future clipping
- **used** — already clipped
- **skipped** — intentionally skipped

Click the status pill or ✏️ button to edit. You can also add:
- Clip title
- Used date
- Local output path
- Published URL
- Notes

### Search
Global search across video titles, channel names, notes, and clip titles.

### Channels
Browse videos grouped by their original YouTube channel. Filter by status including **"Not Used Yet"** to find unclipped content.

### Duplicates
Find videos that appear in multiple playlists/sources.

### Export
- **Export JSON** — full data dump
- **Export CSV** — video list with statuses

### Clipping Command
Click 📋 on any video to copy the clipping command:
```bash
python main.py --url "https://www.youtube.com/watch?v=..."
```
Configure default flags in **Settings** (clips, ratio, font-style, etc.).

## 📸 Snapshot Behavior

> **This is a local snapshot tracker, not a live sync.**

- Data is fetched from YouTube **only** when you add a playlist or click **Pull Again**
- Opening the dashboard **does not** call YouTube
- Opening a playlist detail **does not** call YouTube
- If the YouTube playlist changes, your local data stays the same until you pull again
- Videos removed from the YouTube playlist are **never deleted** from your database

## 🗄️ Database

SQLite database at: `youtube_tracker/youtube_tracker.sqlite3`

### Schema Overview

| Table | Purpose |
|-------|---------|
| `channels` | YouTube channels |
| `sources` | Playlists, manual source, channel sources |
| `videos` | Unique videos by `youtube_video_id` |
| `source_videos` | Many-to-many: which videos belong to which sources |
| `video_status` | Global status per video (unused/candidate/used/skipped) |
| `pull_runs` | History of playlist pulls |
| `pull_run_videos` | Videos seen in each pull |
| `clips` | Multiple clip outputs per video (future use) |
| `tags` / `video_tags` | Tagging system (future use) |
| `settings` | Key-value settings store |

### Relationships

- A **video** can appear in multiple **sources** (playlists)
- A **video** has exactly one **status** (global, not per-source)
- A **video** belongs to one **channel** (the original uploader)
- A **source** (playlist) has an **owner channel** which may differ from video channels
- **Pull runs** track the history of each playlist refresh

## 🔧 Troubleshooting

### yt-dlp fails to fetch metadata

```
Error: Could not fetch metadata
```

1. Update yt-dlp: `pip install -U yt-dlp`
2. Check if the video/playlist is private or age-restricted
3. Check your network connection
4. Some videos may be unavailable in your region

### Server won't start

- Ensure port 8765 is not in use
- Ensure Python 3.10+ is installed
- Check if `yt-dlp` is installed: `python -c "import yt_dlp; print(yt_dlp.version.__version__)"`

### Database issues

Delete `youtube_tracker/youtube_tracker.sqlite3` and restart the server to recreate from scratch. All data will be lost.

## ⚠️ Limitations (v1)

- Playlist fetching is **synchronous** — large playlists (500+ videos) may take a while
- No background worker / async fetching yet
- No authentication — runs locally only
- Tags feature (tables ready, UI not yet implemented)
- Clips table (ready for multiple outputs per video, UI not yet implemented)

## 📁 File Structure

```
youtube_tracker/
├── README.md              # This file
├── server.py              # HTTP server + API endpoints
├── db.py                  # SQLite database layer
├── youtube_fetcher.py     # yt-dlp wrapper for metadata
├── youtube_tracker.sqlite3 # Database (auto-created)
└── static/
    ├── index.html         # SPA shell
    ├── app.js             # Vanilla JS frontend
    └── style.css          # Dark mode design system
```
