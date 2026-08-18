from __future__ import annotations

import io
import math
import struct
from dataclasses import dataclass
from typing import Iterable

from PIL import Image, ImageOps, ImageStat


ENCODER_NAME = "localhub-fingerprint-v1"
GRID = 4
GRAY_SIZE = 8
HIST_BINS = 8


def normalize(vector: Iterable[float]) -> tuple[float, ...]:
    values = tuple(float(x) for x in vector)
    norm = math.sqrt(sum(x * x for x in values))
    if norm <= 1e-12:
        return tuple(0.0 for _ in values)
    return tuple(x / norm for x in values)


def cosine(left: Iterable[float], right: Iterable[float]) -> float:
    a = tuple(left)
    b = tuple(right)
    if not a or len(a) != len(b):
        return 0.0
    return max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b))))


def mean_vector(vectors: list[tuple[float, ...]]) -> tuple[float, ...]:
    if not vectors:
        return ()
    dims = len(vectors[0])
    acc = [0.0] * dims
    count = 0
    for vector in vectors:
        if len(vector) != dims:
            continue
        count += 1
        for i, value in enumerate(vector):
            acc[i] += value
    if not count:
        return ()
    return normalize(value / count for value in acc)


def pack_vector(vector: Iterable[float]) -> bytes:
    values = tuple(float(x) for x in vector)
    return struct.pack("<H", len(values)) + struct.pack(f"<{len(values)}f", *values)


def unpack_vector(data: bytes | None) -> tuple[float, ...]:
    if not data or len(data) < 2:
        return ()
    dims = struct.unpack_from("<H", data, 0)[0]
    expected = 2 + dims * 4
    if dims <= 0 or len(data) != expected:
        return ()
    return tuple(struct.unpack_from(f"<{dims}f", data, 2))


@dataclass(frozen=True)
class EncodedFrame:
    vector: tuple[float, ...]
    quality: float


class FingerprintEncoder:
    """Dependency-light visual encoder used as the safe first-stage baseline.

    This is deliberately *not* a CLIP replacement. It creates a compact visual
    fingerprint from color, coarse spatial layout and luminance. It is useful
    for learning prototypes from the user's already-confirmed tags, while the
    surrounding index/scheduler API stays compatible with a future ONNX
    image-text encoder.
    """

    name = ENCODER_NAME

    def encode_jpeg(self, data: bytes) -> EncodedFrame | None:
        try:
            with Image.open(io.BytesIO(data)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                # Preserve the whole frame. Padding is more stable than cropping
                # for portrait/landscape media and costs almost nothing.
                image.thumbnail((160, 160), Image.Resampling.BILINEAR)
                canvas = ImageOps.pad(image, (128, 128), method=Image.Resampling.BILINEAR, color=(16, 16, 16))
        except Exception:
            return None

        features: list[float] = []

        # Global per-channel histogram: robust to modest crop/layout changes.
        channels = canvas.split()
        for channel in channels:
            hist = channel.histogram()
            for bucket in range(HIST_BINS):
                lo = bucket * 256 // HIST_BINS
                hi = (bucket + 1) * 256 // HIST_BINS
                features.append(sum(hist[lo:hi]) / float(128 * 128))

        # Coarse 4x4 spatial RGB means keep basic composition information.
        step = 128 // GRID
        for gy in range(GRID):
            for gx in range(GRID):
                crop = canvas.crop((gx * step, gy * step, (gx + 1) * step, (gy + 1) * step))
                mean = ImageStat.Stat(crop).mean
                features.extend(value / 255.0 for value in mean[:3])

        # Low-frequency luminance layout. Center around 0 so uniform brightness
        # does not dominate cosine similarity.
        gray = canvas.convert("L").resize((GRAY_SIZE, GRAY_SIZE), Image.Resampling.BILINEAR)
        pixels = [value / 255.0 for value in gray.getdata()]
        avg = sum(pixels) / len(pixels)
        variance = sum((value - avg) ** 2 for value in pixels) / len(pixels)
        features.extend(value - avg for value in pixels)

        # Simple gradient summary, enough to distinguish very flat/structured
        # frames without adding a heavyweight vision dependency.
        edge_h = [0.0] * GRID
        edge_v = [0.0] * GRID
        matrix = list(gray.getdata())
        for y in range(GRAY_SIZE):
            for x in range(GRAY_SIZE):
                here = matrix[y * GRAY_SIZE + x]
                if x + 1 < GRAY_SIZE:
                    edge_h[min(GRID - 1, x * GRID // GRAY_SIZE)] += abs(matrix[y * GRAY_SIZE + x + 1] - here) / 255.0
                if y + 1 < GRAY_SIZE:
                    edge_v[min(GRID - 1, y * GRID // GRAY_SIZE)] += abs(matrix[(y + 1) * GRAY_SIZE + x] - here) / 255.0
        features.extend(value / GRAY_SIZE for value in edge_h)
        features.extend(value / GRAY_SIZE for value in edge_v)

        quality = min(1.0, math.sqrt(max(0.0, variance)) * 4.0)
        return EncodedFrame(normalize(features), quality)


DEFAULT_ENCODER = FingerprintEncoder()
