from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def apply_transition(clip_a: Path, clip_b: Path, config, output: Path) -> Path:
    """Apply a transition between *clip_a* and *clip_b* using cut-fx.

    Args:
        clip_a: Path to first clip.
        clip_b: Path to second clip.
        config: TransitionRef (has .type and .duration).
        output: Path for the output clip.

    Returns:
        Path to the joined clip.
    """
    try:
        from cut_fx import apply_transition as _apply
    except ImportError as exc:
        raise RuntimeError(
            "cut-fx is required for transitions — pip install cut-fx"
        ) from exc

    transition_type = config.type if config else "dissolve_ii"
    duration = config.duration if config else 0.5

    output = Path(output)
    try:
        return Path(_apply(
            clip_a=clip_a,
            clip_b=clip_b,
            transition=transition_type,
            output=output,
            overlap_seconds=duration,
        ))
    except Exception as exc:
        logger.warning(
            "Transition %r failed (%s) — falling back to hard cut", transition_type, exc
        )
        return _hard_cut(clip_a, clip_b, output)


def _hard_cut(clip_a: Path, clip_b: Path, output: Path) -> Path:
    """Concatenate two clips without a transition."""
    import subprocess, tempfile, os
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(f"file '{clip_a.as_posix()}'\n")
        f.write(f"file '{clip_b.as_posix()}'\n")
        concat_list = f.name

    result = subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
         "-i", concat_list, "-c", "copy", str(output)],
        capture_output=True, text=True,
    )
    os.unlink(concat_list)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg hard-cut concat failed: {result.stderr[:500]}")
    return output
