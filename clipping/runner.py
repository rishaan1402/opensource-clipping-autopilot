"""
clipping.runner — Pipeline Orchestrator

Maps to Cell 4 (Execute) of the notebook.
Orchestrates the full clip generation pipeline.
"""

import json
import os

from . import diarization as diarization_mod
from . import engine, metadata, studio, hook_manager, voiceover, rights
from .phase1.checkpoint import CheckpointManager


def run_pipeline(cfg) -> list[dict]:
    """
    Run the full clipping pipeline:
      1. Download YouTube video
      2. Transcribe with Whisper
      3. Analyse with Gemini AI
      4. Normalize metadata
      5. Prepare glitch transition
      6. Render each clip
      7. Save render_manifest.json

    Steps 1, 2, and each per-clip render in step 6 are checkpointed
    (clipping.phase1.checkpoint) so a crashed or interrupted run can be
    resumed without redoing expensive work, unless --no-checkpoint is set.

    Parameters
    ----------
    cfg : SimpleNamespace
        Configuration object from ``config.build_config()``.

    Returns
    -------
    list[dict]
        Render manifest (one dict per clip).
    """
    use_checkpoint = getattr(cfg, "enable_checkpoint", True)
    checkpoint = CheckpointManager(cfg.outputs_dir, source_key=getattr(cfg, "source_url", None))
    if getattr(cfg, "reset_checkpoint", False):
        checkpoint.reset()

    # Step 0 — Deduplication check (warns only; never silently blocks a run —
    # use --force-reprocess to suppress the warning once you've decided to proceed)
    dedup = None
    dedup_source = None
    if getattr(cfg, "source_url", None):
        from .phase1.deduplication import DeduplicationManager
        from .phase1.input_handler import InputSource

        dedup_dir = getattr(cfg, "dedup_db_dir", None) or os.path.join(
            os.path.dirname(cfg.outputs_dir.rstrip(os.sep)), "data"
        )
        dedup = DeduplicationManager(dedup_dir)
        try:
            dedup_source = InputSource(source=cfg.source_url)
            existing = dedup.check_video_duplicate(dedup_source)
        except ValueError:
            existing = None

        if existing and not getattr(cfg, "force_reprocess", False):
            print(
                f"⚠️  This video was already processed on {existing['processed_date']} "
                f"(output: {existing['output_dir']}). Continuing to reprocess — "
                f"use --force-reprocess to suppress this warning."
            )

    # Step 1 — Download
    source_platform = getattr(cfg, "source_platform", "youtube")
    source_info = {}
    if (
        use_checkpoint
        and checkpoint.is_step_complete("download")
        and os.path.exists(cfg.source_video_file)
    ):
        print(f"⏭️  [1/3] Download skipped (checkpoint: already done) — {cfg.source_video_file}")
        source_info = checkpoint.get_step_data("download") or {}
    else:
        source_info = engine.download_video(
            cfg.source_url,
            cfg.source_video_file,
            getattr(cfg, "use_dlp_subs", False),
            getattr(cfg, "download_source_height", "max"),
            source_platform=source_platform,
            cookies_file=getattr(cfg, "cookies_file", None),
        )
        if use_checkpoint:
            checkpoint.mark_step_complete(
                "download", {"file": cfg.source_video_file, **source_info}
            )

    # Step 1.5 — Source-rights gate. Re-checked here (not just at CLI-parse
    # time) because a licensed_cc video's license, or a permissioned
    # creator's agreement, can both change between queueing and processing —
    # and this runs before Whisper/Gemini spend anything on the source.
    rights.enforce_source_rights_or_raise(cfg, source_info)

    # Step 2 — Transcribe
    full_transcript = ""
    segment_data = []

    if use_checkpoint and checkpoint.is_step_complete("transcribe"):
        cached = checkpoint.get_step_data("transcribe")
        full_transcript = cached.get("full_transcript", "")
        segment_data = cached.get("segment_data", [])
        print("⏭️  [2/3] Transcription skipped (checkpoint: already done)")

    if not full_transcript or not segment_data:
        import glob

        # Look for any json3 file (language could be .id.json3 or .en.json3)
        json3_files = glob.glob(cfg.source_video_file.replace(".mp4", ".*.json3"))
        file_json3 = json3_files[0] if json3_files else None

        # Only run YouTube JSON3 subtitle search for YouTube sources
        if source_platform == "youtube":
            if (
                getattr(cfg, "use_dlp_subs", False)
                and file_json3
                and os.path.exists(file_json3)
            ):
                full_transcript, segment_data = engine.parse_youtube_json3_subs(
                    file_json3, max_words_per_subtitle=cfg.max_words_per_subtitle
                )
                if full_transcript and segment_data:
                    print(
                        f"✅ Successfully parsed subtitle from YouTube ({os.path.basename(file_json3)}), skipping Whisper."
                    )

        if not full_transcript or not segment_data:
            full_transcript, segment_data = engine.transcribe_video(
                cfg.source_video_file,
                max_words_per_subtitle=cfg.max_words_per_subtitle,
                model_size=cfg.whisper_model,
                device=cfg.whisper_device,
                compute_type=cfg.whisper_compute_type,
            )

        if use_checkpoint:
            checkpoint.mark_step_complete(
                "transcribe",
                {"full_transcript": full_transcript, "segment_data": segment_data},
            )

    # Step 3 — Gemini AI analysis
    gemini_output_path = os.path.join(cfg.outputs_dir, "gemini_response.json")
    
    if getattr(cfg, "load_gemini_json", False) and os.path.exists(gemini_output_path):
        print(f"\n🔄 [3/3] Loading AI data ({cfg.ai_provider}) from local file: {gemini_output_path}")
        with open(gemini_output_path, "r", encoding="utf-8") as f:
            result_json = json.load(f)
    else:
        result_json = engine.analyze_with_ai(full_transcript, cfg)
        
        # Save raw gemini json for future loading/reproduction
        with open(gemini_output_path, "w", encoding="utf-8") as f:
            json.dump(result_json, f, indent=4, ensure_ascii=False)
        print(f"💾 Raw AI response saved to: {gemini_output_path}")

    if use_checkpoint:
        checkpoint.mark_step_complete("ai_analysis", {"path": gemini_output_path})

    # Step 3.5 — Attribution. Populates the 'source_url' field that
    # metadata._build_youtube_description() already knows how to render as
    # a "Source: ..." line — owed for licensed_cc/permissioned (legally, for
    # CC-BY) and for transformed_commentary (discloses what's being
    # commented on, which also strengthens the fair-use position).
    attribution = rights.build_attribution_source_url(cfg, source_info)
    if attribution:
        for clip in result_json:
            clip["source_url"] = attribution

    # Step 4 — Metadata normalisation
    result_json = metadata.normalize_and_validate(result_json)

    # Step 4.1 — Boundary correction: check the AI's chosen end_time (and,
    # lightly, start_time) against Whisper's word-level timestamps so clips
    # don't end mid-sentence. Runs before dedup/scoring below so their
    # transcript-text extraction reflects the corrected window, not the
    # AI's raw one.
    if getattr(cfg, "enable_boundary_correction", True) and segment_data:
        from .phase1.boundary_correction import correct_clip_boundaries

        try:
            result_json = correct_clip_boundaries(
                result_json,
                segment_data,
                max_duration=getattr(cfg, "max_clip_duration", engine.MAX_CLIP_DURATION),
                max_extension_seconds=getattr(cfg, "max_boundary_extension", 12.0),
            )
        except Exception as e:
            print(f"⚠️ Boundary correction failed: {e}. Continuing with AI-chosen timestamps as-is.")

    metadata.print_preview(result_json)

    metadata_path = os.path.join(cfg.outputs_dir, "metadata_preview.json")
    metadata.save_metadata_preview(result_json, path=metadata_path)

    # Step 4.4 — Semantic dedup (optional, feature-flagged): drops AI-selected
    # candidates that are near-duplicates of a higher-scoring one in the same
    # batch, before spending render/scoring work on them.
    if getattr(cfg, "enable_semantic_dedup", True):
        from .phase1.semantic_dedup import deduplicate_candidates

        before_count = len(result_json)
        try:
            result_json = deduplicate_candidates(
                result_json,
                segment_data,
                threshold=getattr(cfg, "semantic_dedup_threshold", 0.92),
                model_name=getattr(cfg, "bge_model", "BAAI/bge-small-en-v1.5"),
            )
            dropped = before_count - len(result_json)
            if dropped:
                print(f"🧹 Semantic dedup dropped {dropped} near-duplicate candidate(s).")
                # Keep 'rank' sequential even if monetization scoring (which
                # otherwise owns re-ranking) is disabled below.
                for idx, item in enumerate(result_json):
                    item["rank"] = idx + 1
        except Exception as e:
            print(f"⚠️ Semantic dedup failed: {e}. Continuing with all candidates.")

    # Step 4.45 — Prosody scoring (optional, feature-flagged): reads the audio-energy
    # signal Whisper's transcription step already decoded but never persisted — needs
    # its own WAV extraction (mirrors the diarization step's own extract_audio call
    # below), reused across candidates rather than re-extracted per window.
    if getattr(cfg, "enable_prosody_scoring", True) and os.path.exists(cfg.source_video_file):
        from .phase1.prosody_scoring import score_candidates_prosody

        try:
            prosody_audio_path = cfg.source_video_file.replace(".mp4", "_prosody_audio.wav")
            if not os.path.exists(prosody_audio_path):
                diarization_mod.extract_audio(cfg.source_video_file, prosody_audio_path)
            result_json = score_candidates_prosody(result_json, prosody_audio_path)
        except Exception as e:
            print(f"⚠️ Prosody scoring failed: {e}. Continuing without prosody signal.")

    # Step 4.46 — Visual-interest scoring (optional, feature-flagged): SigLIP
    # zero-shot-scores a handful of sampled frames per candidate against fixed
    # "engaging" vs "boring" text prompts — a different signal than the has_face/
    # has_motion probe below, which is boolean and only samples the opening window.
    if getattr(cfg, "enable_visual_scoring", True) and os.path.exists(cfg.source_video_file):
        from .phase1.visual_scoring import score_candidates_visual

        try:
            result_json = score_candidates_visual(
                result_json,
                cfg.source_video_file,
                model_name=getattr(cfg, "siglip_model", "google/siglip-base-patch16-224"),
            )
        except Exception as e:
            print(f"⚠️ Visual scoring failed: {e}. Continuing without visual signal.")

    # Step 4.5 — Monetization scoring (optional, feature-flagged)
    from .phase1.candidate_scoring import score_candidates, write_candidates_artifact

    if getattr(cfg, "enable_monetization_scoring", True):
        # Cheap has_face/has_motion probe (a handful of sampled frames per
        # candidate, not a full render pass) — feeds the VVSA sub-score real
        # visual signal instead of leaving it permanently unknown. Skipped
        # for non-video source paths (e.g. json3-only reruns) that don't
        # have the source file locally.
        if os.path.exists(cfg.source_video_file):
            for clip in result_json:
                probe = studio.quick_face_motion_probe(
                    cfg.source_video_file,
                    float(clip.get("start_time", 0.0)),
                    float(clip.get("end_time", 0.0)),
                    cfg,
                )
                clip["has_face"] = probe["has_face"]
                clip["has_motion"] = probe["has_motion"]

        result_json = score_candidates(
            result_json,
            segment_data,
            quality_weight=getattr(cfg, "monetization_quality_weight", 0.7),
            monetization_weight=getattr(cfg, "monetization_weight", 0.3),
            prosody_weight=getattr(cfg, "prosody_weight", 0.0),
            visual_weight=getattr(cfg, "visual_weight", 0.0),
        )
        # Re-rank by combined_score, reassign sequential rank (mirrors
        # metadata.py's own sort-then-reassign-rank pattern).
        result_json = sorted(result_json, key=lambda x: x["combined_score"], reverse=True)
        for idx, item in enumerate(result_json):
            item["rank"] = idx + 1
        print(
            f"💰 Monetization scoring applied "
            f"(quality={cfg.monetization_quality_weight}, monetization={cfg.monetization_weight}, "
            f"prosody={getattr(cfg, 'prosody_weight', 0.0)}, "
            f"visual={getattr(cfg, 'visual_weight', 0.0)}) "
            f"— clips re-ranked by combined_score."
        )

    candidates_path = os.path.join(cfg.outputs_dir, "clip_candidates.json")
    write_candidates_artifact(result_json, candidates_path)
    print(f"💾 Clip candidates saved to {candidates_path}")

    # Step 5 — Diarization (split-screen / camera-switch)
    diarization_data = None
    if (
        (getattr(cfg, "use_split_screen", False) and cfg.split_trigger == "diarization")
        or getattr(cfg, "use_camera_switch", False)
    ) and studio._is_vertical_ratio(cfg.aspect_ratio):
        try:
            mode_label = (
                "Split-Screen"
                if getattr(cfg, "use_split_screen", False)
                else "Camera-Switch"
            )
            print(f"\n🎙️ [{mode_label}] Running speaker diarization...")
            audio_path = cfg.source_video_file.replace(".mp4", "_audio.wav")
            diarization_mod.extract_audio(cfg.source_video_file, audio_path)
            num_speakers_arg = getattr(cfg, "diarization_num_speakers", 2)
            min_spk = None
            max_spk = None

            if str(num_speakers_arg).lower() == "auto":
                max_faces = studio.estimate_speaker_count_from_video(
                    cfg.source_video_file, cfg
                )
                num_speakers_arg = "auto"
                min_spk = max(1, max_faces)
                max_spk = min_spk + 2
                print(f"   ℹ️ Instruksi Pyannote: {min_spk} hingga {max_spk} speaker.")

            diarization_data = diarization_mod.run_diarization(
                audio_path,
                hf_token=cfg.hf_token,
                num_speakers=num_speakers_arg,
                min_speakers=min_spk,
                max_speakers=max_spk,
            )
            # Clean up temp audio
            if os.path.exists(audio_path):
                os.remove(audio_path)
        except Exception as e:
            print(f"⚠️ Diarization failed: {e}")
            print("   Falling back to normal render mode (without split-screen).")
            diarization_data = None

    # Step 6 — Video encoder & glitch
    os.environ["OSC_VIDEO_SCALE_ALGO"] = str(
        getattr(cfg, "video_scale_algo", "lanczos")
    )
    
    # Get target dimensions for auto-bitrate calculation
    import cv2
    cap_e = cv2.VideoCapture(cfg.source_video_file)
    src_h_e = int(cap_e.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap_e.release()
    
    target_w_e, target_h_e = studio._get_render_dims(cfg, cfg.aspect_ratio, source_h=src_h_e)
    video_encoder = studio.detect_video_encoder(cfg, target_h=target_h_e)

    file_glitch_ts = None
    if cfg.use_hook_glitch:
        print("⚙️ Menyiapkan Video Glitch Transisi...")
        
        # Get source dimensions for proper glitch scaling
        import cv2
        cap_g = cv2.VideoCapture(cfg.source_video_file)
        source_h_g = int(cap_g.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap_g.release()

        file_glitch_ts = studio.prepare_glitch_video(
            cfg.aspect_ratio, cfg, video_encoder, source_h=source_h_g
        )

    # Step 6 — Render each clip
    render_manifest: list[dict] = []

    custom_hook_path = None
    if getattr(cfg, "hook_source", None):
        print("\n🎣 Downloading custom hook clip source...")
        custom_hook_path = hook_manager.download_custom_hook(cfg)

    # Step 5.5 — Generate Voice-Over (if enabled)
    if getattr(cfg, "voiceover", False):
        print(f"\n🎙️ Generating Voice-Over for {len(result_json)} clips...")
        for clip in result_json:
            try:
                # 1. Generate commentary script from snippet
                start = float(clip["start_time"])
                end = float(clip["end_time"])
                # Extract transcript snippet for this time range
                snippet_lines = []
                for seg in segment_data:
                    if float(seg["end"]) > start and float(seg["start"]) < end:
                        # Support both Whisper format (has 'text') and YouTube JSON3 (only 'words')
                        seg_text = seg.get("text") or " ".join(w["word"] for w in seg.get("words", []))
                        if seg_text:
                            snippet_lines.append(seg_text)
                snippet_text = " ".join(snippet_lines)

                script = voiceover.generate_commentary_script(
                    snippet_text,
                    cfg,
                    style=cfg.voiceover_style,
                    language=cfg.voiceover_lang,
                    length=cfg.voiceover_length,
                    strict_commentary=(
                        getattr(cfg, "source_rights", rights.RIGHTS_UNKNOWN)
                        == rights.RIGHTS_TRANSFORMED_COMMENTARY
                    ),
                )

                if script:
                    # 2. Synthesize TTS
                    audio_path, vo_segments = voiceover.synthesize_voice(
                        script,
                        cfg.voiceover_voice,
                        cfg.outputs_dir,
                        str(clip["rank"])
                    )
                    
                    if os.path.exists(audio_path):
                        clip["voiceover"] = {
                            "script": script,
                            "audio_path": audio_path,
                            "segments": vo_segments,
                            "voice": cfg.voiceover_voice
                        }

            except Exception as e:
                print(f"   ⚠️ Failed to generate voice-over for Rank {clip['rank']}: {e}")

    for clip in sorted(result_json, key=lambda x: x["rank"]):

        if custom_hook_path:
            clip["custom_hook_info"] = {"file_path": custom_hook_path}

        rank = clip["rank"]
        step_name = f"render_clip_{rank}"

        if use_checkpoint and checkpoint.is_step_complete(step_name):
            cached = checkpoint.get_step_data(step_name) or {}
            cached_entry = cached.get("manifest_entry")
            cached_video_path = cached_entry.get("video_path") if cached_entry else None
            if (
                cached_entry
                and cached_entry.get("status") == "success"
                and cached_video_path
                and os.path.exists(cached_video_path)
            ):
                print(f"⏭️  Rank {rank} skipped (checkpoint: already rendered) — {cached_video_path}")
                render_manifest.append(cached_entry)
                continue
            # Cached but not a usable success (missing file / prior failure) — re-render.

        render_result = studio.process_clip(
            clip["rank"],
            clip,
            cfg.aspect_ratio,
            file_glitch_ts,
            segment_data,
            cfg,
            video_encoder,
            diarization_data=diarization_data,
        )
        if render_result:
            render_manifest.append(render_result)

        if use_checkpoint and render_result:
            if render_result.get("status") == "success":
                checkpoint.mark_step_complete(step_name, {"manifest_entry": render_result})
            else:
                checkpoint.mark_step_failed(step_name, render_result.get("error", "unknown render error"))

    # Step 7 — Inject source metadata for attribution & safety tracking
    for row in render_manifest:
        # Attach source URL so metadata.py can auto-add source credit
        if not row.get("source_url"):
            row["source_url"] = getattr(cfg, "source_url", None)

    # Step 8 — Save manifest
    manifest_path = os.path.join(cfg.outputs_dir, "render_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(render_manifest, f, ensure_ascii=False, indent=2)

    print(
        f"\n💾 Render manifest disimpan ke {manifest_path} ({len(render_manifest)} item)"
    )

    # Step 9 — Quality control on rendered clips (optional, feature-flagged)
    if getattr(cfg, "enable_quality_control", True):
        from .phase1.quality_control import QualityControlManager

        qc = QualityControlManager(strict_mode=getattr(cfg, "qc_strict", False))
        qc_summary = qc.validate_all_clips(cfg.outputs_dir)
        qc.print_summary(qc_summary)

        qc_path = os.path.join(cfg.outputs_dir, "quality_report.json")
        with open(qc_path, "w", encoding="utf-8") as f:
            json.dump(qc_summary, f, ensure_ascii=False, indent=2)
        print(f"💾 Quality report saved to {qc_path}")

    # Step 10 — Record this video as processed (deduplication)
    if dedup is not None and dedup_source is not None and render_manifest:
        dedup.record_video(dedup_source, cfg.source_video_file, cfg.outputs_dir)

    return render_manifest

