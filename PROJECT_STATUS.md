# YouTube Clipper — Project Status & Roadmap

_Last updated after wiring Phase 1 foundation modules into the real pipeline
and verifying with an actual end-to-end run against real video, real Whisper
transcription, real Gemini analysis, and real ffmpeg rendering._

## ✅ What's Actually Wired Into the Real Pipeline

Running `python main.py --url ...` now executes all of the following:

### 1. Monetization Scoring (`clipping/phase1/monetization.py` + `candidate_scoring.py`)
- Hook strength, VVSA prediction, retention-curve fit, optimal length, series
  detection — combined into a `combined_score` (70% AI viral_score / 30%
  monetization by default, configurable via `--quality-weight` /
  `--monetization-weight`)
- Clips re-ranked by `combined_score`, written to `outputs/clip_candidates.json`
- Feature flag: `--no-monetization-scoring`
- **46 + 21 = 67 tests**

### 2. Checkpoint & Resume (`clipping/phase1/checkpoint.py`)
- Download, transcription, and each per-clip render are checkpointed under
  `outputs/.checkpoints/pipeline_state.json`
- A crashed/interrupted run resumes without redoing expensive work (skips
  re-download if the file exists, skips re-transcription if cached, skips
  re-rendering a clip whose output file still exists)
- Feature flags: `--no-checkpoint`, `--reset-checkpoint`
- **16 tests** — including a real bug found and fixed: `_init_state()`
  never loaded existing state on a second `CheckpointManager` instance
  pointed at the same directory (the exact resume-after-crash scenario),
  it silently left `self.state` unset

### 3. Quality Control (`clipping/phase1/quality_control.py`)
- Every rendered clip is validated post-render: duration bounds (aligned to
  the base pipeline's own 20-179s range, not an assumed 60s Shorts limit),
  audio level (catches silent renders), file integrity
- Results written to `outputs/quality_report.json`
- Feature flags: `--no-quality-control`, `--qc-strict`
- **17 tests** — found and fixed a real bug: both this module and
  `input_handler.py` built an `ffprobe` command with a `noescapes=1`
  sub-option that doesn't exist on the `default` output writer; every
  duration/audio check was silently failing until this was caught by
  writing tests against a real ffmpeg build (not mocks)

### 4. Deduplication (`clipping/phase1/deduplication.py`)
- Before running, checks if this URL (or, for local files, this exact file
  content via hash) was already processed — warns, does not silently block
- After a successful run, records the video as processed
- Feature flags: `--force-reprocess` (suppress the warning), `--dedup-db-dir`
- **17 tests** — found and fixed a real bug: `clear_database()` called
  `self._init_db()`, a method that only exists on the inner `DeduplicationDB`
  class, not on `DeduplicationManager` itself — always raised `AttributeError`

### 5. Batch Mode (`clipping/phase1/input_handler.py` + new `batch_runner.py`)
- `main.py --batch-file videos.csv` (or `.json` / `.txt`) processes multiple
  videos in one invocation
- Each item gets its own **isolated** `outputs/batch/<slug>/` directory —
  no collision on checkpoint state, downloaded files, or render manifests
  between batch items
- A failure in one item doesn't abort the rest of the batch
- Local-file sources correctly skip the (inapplicable) download step by
  pre-seeding that item's checkpoint
- `outputs/batch_report.json` summarizes the run
- **19 (input_handler) + 16 (batch_runner) = 35 tests**

**Total: 152 tests, all passing, run against a real ffmpeg build (not
skipped/mocked for the parts that touch real files).**

---

## ⚠️ Coded But Still Not Wired

**`clipping/phase1/hybrid_scoring.py`** (text + audio + scene-cut segment
scoring) remains standalone. It was designed for a different paradigm than
this base pipeline actually uses: this pipeline has Gemini read the *entire*
transcript and pick clip candidates itself, whereas `hybrid_scoring.py`
scores individual pre-segmented transcript chunks — the two don't compose
cleanly without either (a) feeding hybrid-scored segments into the Gemini
prompt as hints (real prompt-engineering risk of degrading Gemini's own
judgment), or (b) building a genuinely separate non-AI clip-selection path.
Neither has been attempted — this is a real, unresolved design question, not
an oversight.

## ❌ Not Started (Original Roadmap Phase 3-5)

- Platform-specific rendering profiles (TikTok vs Shorts vs Reels dimensions/codecs)
- Smart thumbnail generation (face/emotion scoring — separate from the base
  pipeline's own existing thumbnail step)
- Auto-metadata generation (separate from what Gemini already produces)
- Celery/Redis parallel batch processing (current batch mode is sequential)
- Intelligent posting scheduler
- Performance tracking / analytics feedback loop
- A/B testing framework

---

## 🗂️ File Structure

```
ytclipper/
├── clipping/
│   ├── phase1/
│   │   ├── monetization.py         (650 lines) — wired via candidate_scoring.py
│   │   ├── candidate_scoring.py    (180 lines) — wired into runner.py Step 4.5
│   │   ├── checkpoint.py           (155 lines) — wired into runner.py Steps 1/2/6
│   │   ├── quality_control.py      (285 lines) — wired into runner.py Step 9
│   │   ├── deduplication.py        (215 lines) — wired into runner.py Step 0/10
│   │   ├── input_handler.py        (285 lines) — wired into main.py batch mode
│   │   ├── batch_runner.py         (120 lines) — wired into main.py batch mode
│   │   ├── hybrid_scoring.py       (350 lines) — NOT wired (see above)
│   │   └── tests/                  (152 tests total)
│   │
│   ├── runner.py       ← orchestrator, now calls checkpoint/dedup/QC/monetization
│   ├── config.py        ← CLI flags for every feature above
│   ├── engine.py, metadata.py, studio/ (base pipeline, largely untouched)
│   └── ...
│
├── main.py              ← single-URL, batch, and story modes
├── .env                 ← GOOGLE_API_KEY (gitignored)
└── outputs/
    ├── .checkpoints/pipeline_state.json
    ├── clip_candidates.json
    ├── quality_report.json
    ├── render_manifest.json
    ├── highlight_rank_N_ready.mp4
    └── batch/<slug>/... (batch mode only)
```

---

## Environment Notes (real gotchas hit during verification)

- **This Mac is Apple Silicon, no CUDA.** `faster-whisper`'s CTranslate2
  backend doesn't support MPS — must run `--whisper-device cpu`.
- **MediaPipe's face detector crashes on this machine's Metal/GPU backend**
  (`Check failed: service_ Service is unavailable` inside
  `DrishtiMetalHelper`) — this is a native abort, not catchable Python-side.
  Use `--face-detector yolo` instead (already a supported flag in the base
  pipeline; requires `pip install ultralytics`).
- **Default Homebrew `ffmpeg` on this machine ships without `libass`** — the
  `subtitles`/`ass` filters don't exist, so caption burning fails outright.
  Fixed by switching to the `homebrew-ffmpeg/ffmpeg` tap (`brew uninstall
  --ignore-dependencies ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg`),
  which lists `libass` as a hard dependency.
- **This same ffmpeg upgrade (8.1 → 9.0.1) broke our own `noescapes=1`
  ffprobe sub-option** — see the Quality Control bug above. A reminder that
  "tests pass" isn't the same as "tests pass against the real toolchain."
- **`GOOGLE_API_KEY`'s default fallback model** (`GEMINI_FALLBACK_MODEL` in
  `config.py`) was pointing at a retired model (`gemini-2.5-flash`, 404s for
  new users) — updated to `gemini-3.6-flash`.
- `cp -r dir/*` does not copy dotfiles on this shell — `.env.sample`,
  `.gitignore`, `.python-version` had to be copied separately after the
  initial repo clone.

---

## Running It

```bash
# Single video
export SSL_CERT_FILE=$(python3 -m certifi)   # macOS cert fix, see above
python main.py --url "https://youtube.com/watch?v=..." \
  --clips 3 --ratio 9:16 --face-detector yolo \
  --whisper-model base --whisper-device cpu --whisper-compute-type int8

# Batch mode
python main.py --batch-file videos.csv --clips 3 --face-detector yolo

# Resume after a crash (automatic — just rerun the same command)
python main.py --url "https://youtube.com/watch?v=..." --clips 3
# → "⏭️  Download dilewati (checkpoint: sudah selesai)" etc.

# Force full redo, ignore all caches
python main.py --url "..." --reset-checkpoint --force-reprocess
```

## Tests

```bash
python3 -m unittest discover clipping/phase1/tests -v
# Ran 152 tests in ~5s, OK
```
