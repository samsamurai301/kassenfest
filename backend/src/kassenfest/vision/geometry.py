Box = tuple[float, float, float, float]
"""left, top, right, bottom in source pixels (right/bottom exclusive)."""


def from_norm1000(box: Box, width: int, height: int) -> Box:
    """Muse Spark returns boxes on a 0–1000 grid and may overshoot slightly; clamp to the image."""
    x0, y0, x1, y1 = (min(max(v, 0.0), 1000.0) for v in box)
    return (x0 * width / 1000, y0 * height / 1000, x1 * width / 1000, y1 * height / 1000)


def iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0
