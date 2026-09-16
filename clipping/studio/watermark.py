"""
clipping.studio.watermark — Watermark Overlay Engine

Modular module for adding a watermark to video frames.
Supports text watermarks and image watermarks (PNG, JPG, JPEG, WEBP)
with auto-scaling, transparency, and 9 anchor positions.

Usage (called per-frame from the renderer):
    from clipping.studio.watermark import apply_watermark
    frame = apply_watermark(frame, cfg)
"""

import os
from abc import ABC, abstractmethod

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


# ==============================================================================
# CONSTANTS & VALIDATION
# ==============================================================================

VALID_POSITIONS = [
    "top-left", "top-center", "top-right",
    "center-left", "center", "center-right",
    "bottom-left", "bottom-center", "bottom-right",
]

DEFAULT_OPACITY = 70
DEFAULT_POSITION = "center-right"
DEFAULT_PADDING = 0
DEFAULT_FONT_SIZE = 0  # 0 = auto (3% of frame height)


def validate_watermark_config(cfg):
    """
    Validate watermark parameters in config.
    Raises ValueError if anything is invalid.
    """
    if not getattr(cfg, "watermark_enabled", False):
        return

    wm_text = getattr(cfg, "watermark_text", None)
    wm_image = getattr(cfg, "watermark_image", None)

    if not wm_text and not wm_image:
        raise ValueError(
            "❌ --watermark requires --text or --image. "
            "Example: --watermark --text \"Watermark Name\""
        )

    opacity = getattr(cfg, "watermark_opacity", DEFAULT_OPACITY)
    if not (1 <= opacity <= 100):
        raise ValueError(
            f"❌ --opacity must be between 1-100, got: {opacity}"
        )

    position = getattr(cfg, "watermark_position", DEFAULT_POSITION)
    if position not in VALID_POSITIONS:
        raise ValueError(
            f"❌ --position '{position}' is invalid. "
            f"Choices: {', '.join(VALID_POSITIONS)}"
        )

    padding = getattr(cfg, "watermark_padding", DEFAULT_PADDING)
    if padding < 0:
        raise ValueError(
            f"❌ --padding cannot be negative, got: {padding}"
        )

    font_size = getattr(cfg, "watermark_font_size", DEFAULT_FONT_SIZE)
    if font_size < 0:
        raise ValueError(
            f"❌ --watermark-font-size cannot be negative, got: {font_size}"
        )

    if wm_image:
        if not os.path.exists(wm_image):
            raise ValueError(
                f"❌ Watermark image file not found: {wm_image}"
            )
        valid_exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff")
        if not wm_image.lower().endswith(valid_exts):
            raise ValueError(
                f"❌ Unsupported watermark file format: {wm_image}. "
                f"Supported formats: {', '.join(valid_exts)}"
            )

    scale = getattr(cfg, "watermark_scale", 15)
    if not (1 <= scale <= 100):
        raise ValueError(
            f"❌ --watermark-scale must be between 1-100, got: {scale}"
        )


# ==============================================================================
# BASE CLASS
# ==============================================================================


class WatermarkRenderer(ABC):
    """Abstract base class for all watermark renderer types."""

    def __init__(self, cfg):
        self.opacity = getattr(cfg, "watermark_opacity", DEFAULT_OPACITY) / 100.0
        self.position = getattr(cfg, "watermark_position", DEFAULT_POSITION)
        self.padding = getattr(cfg, "watermark_padding", DEFAULT_PADDING)

    def _calculate_position(self, frame_w, frame_h, wm_w, wm_h):
        """
        Calculate (x, y) coordinates for the watermark based on position and padding.

        Padding is applied from the nearest side according to position:
        - top-left     → padding from top and left
        - center-right → padding from the right, vertically centered
        - center       → padding ignored, exactly centered
        - etc.

        Returns:
            tuple[int, int]: (x, y) coordinates for the watermark's top-left corner.
        """
        pad = self.padding

        # Horizontal position
        if "left" in self.position:
            x = pad
        elif "right" in self.position:
            x = frame_w - wm_w - pad
        else:  # center horizontally
            x = (frame_w - wm_w) // 2

        # Vertical position
        if self.position.startswith("top"):
            y = pad
        elif self.position.startswith("bottom"):
            y = frame_h - wm_h - pad
        else:  # center vertically
            y = (frame_h - wm_h) // 2

        return max(0, x), max(0, y)

    @abstractmethod
    def render(self, frame):
        """
        Apply the watermark to an OpenCV frame (BGR).

        Args:
            frame: BGR numpy array from OpenCV.

        Returns:
            BGR numpy array with the watermark overlaid.
        """
        pass


# ==============================================================================
# TEXT WATERMARK (Phase 1)
# ==============================================================================


class TextWatermarkRenderer(WatermarkRenderer):
    """
    Renders a text watermark using PIL for good font quality.
    The font is cached after the first load for per-frame performance.
    """

    def __init__(self, cfg):
        super().__init__(cfg)
        self.text = getattr(cfg, "watermark_text", "")
        self.font_size_setting = getattr(cfg, "watermark_font_size", DEFAULT_FONT_SIZE)
        self._font_cache = {}  # Cache font per size
        self._overlay_cache = {}  # Cache rendered overlay per (frame_w, frame_h)

        # Look for a Montserrat font from the project (already used by the subtitle system)
        base_dir = getattr(cfg, "base_dir", os.getcwd())
        font_dir = getattr(cfg, "font_dir", os.path.join(base_dir, "custom_fonts"))

        self._font_path = None
        # Priority: Montserrat-Black > Montserrat-Regular > fallback
        for font_file in ["Montserrat-Black.ttf", "Montserrat-Regular.ttf"]:
            candidate = os.path.join(font_dir, font_file)
            if os.path.exists(candidate):
                self._font_path = candidate
                break

    def _get_font(self, size):
        """Get PIL font object, cached per size."""
        if size not in self._font_cache:
            if self._font_path and os.path.exists(self._font_path):
                self._font_cache[size] = ImageFont.truetype(self._font_path, size)
            else:
                # Fallback to PIL default
                try:
                    self._font_cache[size] = ImageFont.truetype("arial.ttf", size)
                except OSError:
                    self._font_cache[size] = ImageFont.load_default()
        return self._font_cache[size]

    def _compute_font_size(self, frame_h):
        """Compute font size: use the setting if > 0, otherwise auto (3% of frame height, min 16px)."""
        if self.font_size_setting > 0:
            return self.font_size_setting
        return max(16, int(frame_h * 0.03))

    def render(self, frame):
        """Apply the text watermark to a BGR frame."""
        if not self.text:
            return frame

        frame_h, frame_w = frame.shape[:2]
        cache_key = (frame_w, frame_h)

        # Use the cached overlay if the frame size matches (very common within 1 clip)
        if cache_key in self._overlay_cache:
            overlay_rgba, x, y = self._overlay_cache[cache_key]
        else:
            font_size = self._compute_font_size(frame_h)
            font = self._get_font(font_size)

            # Measure the text using PIL
            dummy_img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
            draw = ImageDraw.Draw(dummy_img)
            bbox = draw.textbbox((0, 0), self.text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]

            # Add a small internal margin
            margin = max(4, font_size // 8)
            wm_w = text_w + margin * 2
            wm_h = text_h + margin * 2

            # Calculate position
            x, y = self._calculate_position(frame_w, frame_h, wm_w, wm_h)

            # Render the text onto an RGBA overlay
            overlay_rgba = Image.new("RGBA", (wm_w, wm_h), (0, 0, 0, 0))
            overlay_draw = ImageDraw.Draw(overlay_rgba)

            # White text with a soft shadow for readability
            shadow_offset = max(1, font_size // 30)
            # Shadow
            overlay_draw.text(
                (margin + shadow_offset, margin + shadow_offset - bbox[1]),
                self.text,
                font=font,
                fill=(0, 0, 0, 180),
            )
            # Main text
            overlay_draw.text(
                (margin, margin - bbox[1]),
                self.text,
                font=font,
                fill=(255, 255, 255, 255),
            )

            self._overlay_cache[cache_key] = (overlay_rgba, x, y)

        # Alpha blend the overlay onto the frame
        wm_w, wm_h = overlay_rgba.size

        # Clamp so it doesn't go past the frame bounds
        x2 = min(x + wm_w, frame_w)
        y2 = min(y + wm_h, frame_h)
        actual_w = x2 - x
        actual_h = y2 - y

        if actual_w <= 0 or actual_h <= 0:
            return frame

        # Convert the frame region to PIL RGBA
        region = frame[y:y2, x:x2]
        region_pil = Image.fromarray(cv2.cvtColor(region, cv2.COLOR_BGR2RGBA))

        # Crop the overlay if needed (edge clipping)
        overlay_crop = overlay_rgba.crop((0, 0, actual_w, actual_h))

        # Apply opacity
        if self.opacity < 1.0:
            # Scale the alpha channel by opacity
            r, g, b, a = overlay_crop.split()
            a = a.point(lambda p: int(p * self.opacity))
            overlay_crop = Image.merge("RGBA", (r, g, b, a))

        # Composite
        region_pil = Image.alpha_composite(region_pil, overlay_crop)

        # Convert back to BGR and write into the frame
        result_bgr = cv2.cvtColor(np.array(region_pil), cv2.COLOR_RGBA2BGR)
        frame[y:y2, x:x2] = result_bgr

        return frame


# ==============================================================================
# IMAGE WATERMARK (Phase 2)
# ==============================================================================


class ImageWatermarkRenderer(WatermarkRenderer):
    """
    Renders an image watermark (PNG, JPG, JPEG, WEBP, etc.).

    Features:
    - Loads the watermark image and converts it to RGBA (supports PNG transparency).
    - Auto-scales based on --watermark-scale (percentage of frame height).
    - Alpha compositing with adjustable opacity.
    - Caches per frame size for optimal per-frame performance.
    """

    DEFAULT_SCALE = 15  # 15% of frame height

    def __init__(self, cfg):
        super().__init__(cfg)
        self.image_path = getattr(cfg, "watermark_image", None)
        self.scale_pct = getattr(cfg, "watermark_scale", self.DEFAULT_SCALE)
        self._overlay_cache = {}  # Cache per (frame_w, frame_h)

        # Load the source image as RGBA at initialization
        self._source_rgba = None
        if self.image_path and os.path.exists(self.image_path):
            try:
                img = Image.open(self.image_path)
                # Convert to RGBA (adds an alpha channel if there isn't one)
                self._source_rgba = img.convert("RGBA")
            except Exception as e:
                print(f"⚠️ Failed to load watermark image: {self.image_path} — {e}")
                self._source_rgba = None

    def _scale_image(self, source_rgba, target_h):
        """
        Scale the watermark image so its height = scale_pct% of the frame height.
        Preserves the image's original aspect ratio.

        Args:
            source_rgba: Source PIL Image RGBA.
            target_h: Target frame height.

        Returns:
            The scaled PIL Image RGBA.
        """
        desired_h = max(8, int(target_h * self.scale_pct / 100.0))
        src_w, src_h = source_rgba.size

        if src_h <= 0:
            return source_rgba

        ratio = desired_h / src_h
        desired_w = max(1, int(src_w * ratio))

        return source_rgba.resize(
            (desired_w, desired_h), Image.LANCZOS
        )

    def render(self, frame):
        """Apply the image watermark to a BGR frame."""
        if self._source_rgba is None:
            return frame

        frame_h, frame_w = frame.shape[:2]
        cache_key = (frame_w, frame_h)

        # Use the cached overlay if the frame size matches
        if cache_key in self._overlay_cache:
            scaled_rgba, x, y = self._overlay_cache[cache_key]
        else:
            # Scale the image to fit the frame
            scaled_rgba = self._scale_image(self._source_rgba, frame_h)
            wm_w, wm_h = scaled_rgba.size

            # Calculate position using the base class
            x, y = self._calculate_position(frame_w, frame_h, wm_w, wm_h)

            self._overlay_cache[cache_key] = (scaled_rgba, x, y)

        # Alpha blend the overlay onto the frame
        wm_w, wm_h = scaled_rgba.size

        # Clamp so it doesn't go past the frame bounds
        x2 = min(x + wm_w, frame_w)
        y2 = min(y + wm_h, frame_h)
        actual_w = x2 - x
        actual_h = y2 - y

        if actual_w <= 0 or actual_h <= 0:
            return frame

        # Convert the frame region to PIL RGBA
        region = frame[y:y2, x:x2]
        region_pil = Image.fromarray(cv2.cvtColor(region, cv2.COLOR_BGR2RGBA))

        # Crop the overlay if needed (edge clipping)
        overlay_crop = scaled_rgba.crop((0, 0, actual_w, actual_h))

        # Apply opacity to the alpha channel
        if self.opacity < 1.0:
            r, g, b, a = overlay_crop.split()
            a = a.point(lambda p: int(p * self.opacity))
            overlay_crop = Image.merge("RGBA", (r, g, b, a))

        # Composite
        region_pil = Image.alpha_composite(region_pil, overlay_crop)

        # Convert back to BGR and write into the frame
        result_bgr = cv2.cvtColor(np.array(region_pil), cv2.COLOR_RGBA2BGR)
        frame[y:y2, x:x2] = result_bgr

        return frame


# ==============================================================================
# FACTORY & PUBLIC API
# ==============================================================================


def create_watermark_renderer(cfg):
    """
    Factory function: build the right renderer based on config.

    Returns:
        WatermarkRenderer | None: Renderer instance, or None if watermark isn't enabled.
    """
    if not getattr(cfg, "watermark_enabled", False):
        return None

    wm_text = getattr(cfg, "watermark_text", None)
    wm_image = getattr(cfg, "watermark_image", None)

    if wm_text:
        return TextWatermarkRenderer(cfg)
    elif wm_image:
        return ImageWatermarkRenderer(cfg)

    return None


# Module-level cached renderer instance per cfg identity
_renderer_cache = {}


def apply_watermark(frame, cfg):
    """
    Apply a watermark to an OpenCV frame (BGR).
    Called per-frame from the renderer. The renderer is cached for performance.

    Args:
        frame: BGR numpy array from OpenCV.
        cfg: Config namespace with watermark settings.

    Returns:
        BGR numpy array (modified in-place if watermark is enabled).
    """
    if not getattr(cfg, "watermark_enabled", False):
        return frame

    # Cache renderer per cfg object identity
    cfg_id = id(cfg)
    if cfg_id not in _renderer_cache:
        _renderer_cache[cfg_id] = create_watermark_renderer(cfg)

    renderer = _renderer_cache[cfg_id]
    if renderer is None:
        return frame

    return renderer.render(frame)
