"""
SigLIP Visual-Interest Scoring

clipping.studio.face_detection.quick_face_motion_probe already gives a
boolean has_face/has_motion signal to clipping.phase1.monetization's VVSA
scoring. SigLIP adds something different: zero-shot semantic scoring of a
few sampled frames per candidate window against a fixed set of
"engaging" vs "boring" text prompts, using SigLIP's native image-text
similarity -- no training, no labeled data, and it catches visual-interest
cues (dynamic action, close-up reactions) that a boolean face/motion flag
and the transcript text alone both miss.
"""

from typing import Dict, List

DEFAULT_SIGLIP_MODEL = "google/siglip-base-patch16-224"

# Kept short and generic on purpose: these are zero-shot prompts, not a
# trained classifier, so overly specific wording just adds noise. Each side
# should describe genuinely opposite visual conditions.
POSITIVE_PROMPTS = [
    "a dynamic action shot",
    "a close-up reaction shot of a person's face",
    "an exciting and visually engaging moment",
]
NEGATIVE_PROMPTS = [
    "a static wide shot with no movement",
    "a boring talking head video with no expression",
    "a plain, visually uninteresting scene",
]

_EMPTY_RESULT = {"visual_interest": 0.0, "frames_sampled": 0}

_model_cache: Dict[str, tuple] = {}


def _get_siglip_model(model_name: str):
    """Lazily load and cache a (model, processor) pair by name."""
    if model_name not in _model_cache:
        from transformers import AutoModel, AutoProcessor

        model = AutoModel.from_pretrained(model_name)
        processor = AutoProcessor.from_pretrained(model_name)
        model.eval()
        _model_cache[model_name] = (model, processor)
    return _model_cache[model_name]


def sample_frames(video_path: str, start: float, end: float, num_frames: int = 4) -> List:
    """Sample `num_frames` RGB frames evenly spaced across [start, end).

    Mirrors clipping.studio.face_detection.quick_face_motion_probe's own
    frame-sampling pattern (cv2.VideoCapture + CAP_PROP_POS_MSEC seeking) for
    consistency. Returns fewer than `num_frames` (possibly zero) if the video
    can't be opened or a seek fails -- never raises.
    """
    import cv2

    frames = []
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return frames

    try:
        duration = max(end - start, 0.01)
        step = duration / num_frames
        for i in range(num_frames):
            t = start + i * step
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ret, frame = cap.read()
            if ret:
                frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    finally:
        cap.release()

    return frames


def score_window_visual(
    video_path: str,
    start: float,
    end: float,
    model_name: str = DEFAULT_SIGLIP_MODEL,
    num_frames: int = 4,
) -> Dict:
    """
    Zero-shot-score one [start, end) window's visual interest.

    Returns:
        {"visual_interest": float (0-1), "frames_sampled": int}
        All-zero (not an exception) if the video can't be read, no frames
        sample successfully, or the model fails to load -- this is a soft
        scoring signal, not a hard requirement.
    """
    try:
        import torch
        from PIL import Image

        frames = sample_frames(video_path, start, end, num_frames)
        if not frames:
            return dict(_EMPTY_RESULT)

        model, processor = _get_siglip_model(model_name)
        pil_frames = [Image.fromarray(f) for f in frames]
        all_prompts = POSITIVE_PROMPTS + NEGATIVE_PROMPTS

        inputs = processor(
            text=all_prompts, images=pil_frames, padding="max_length", return_tensors="pt"
        )
        with torch.no_grad():
            outputs = model(**inputs)

        # SigLIP is trained with a sigmoid loss (not softmax/contrastive like
        # CLIP), so per-prompt probabilities from logits_per_image are read
        # with sigmoid, not softmax -- see the SigLIP paper / HF model card.
        probs = torch.sigmoid(outputs.logits_per_image)  # [num_frames, num_prompts]
        pos_score = probs[:, : len(POSITIVE_PROMPTS)].mean().item()
        neg_score = probs[:, len(POSITIVE_PROMPTS):].mean().item()

        total = pos_score + neg_score
        visual_interest = pos_score / total if total > 1e-9 else 0.5

        return {"visual_interest": float(visual_interest), "frames_sampled": len(frames)}
    except Exception:
        return dict(_EMPTY_RESULT)


def score_candidates_visual(
    candidates: List[Dict],
    video_path: str,
    model_name: str = DEFAULT_SIGLIP_MODEL,
    num_frames: int = 4,
) -> List[Dict]:
    """
    Attach visual features + 'visual_score' (0-1) to each candidate, mutating
    and returning the same list (mirrors score_candidates_prosody's
    convention). Unlike prosody's raw energy/pitch features, SigLIP's
    zero-shot score is already comparable across candidates on its own
    scale, so no batch-level min-max normalization is needed here.
    """
    if not candidates:
        return candidates

    for clip in candidates:
        start = float(clip.get("start_time", 0.0))
        end = float(clip.get("end_time", 0.0))
        raw = score_window_visual(video_path, start, end, model_name, num_frames)
        clip["visual"] = raw
        clip["visual_score"] = raw["visual_interest"]

    return candidates
