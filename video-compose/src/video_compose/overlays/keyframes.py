from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from video_compose.schema.spec import Keyframe


def build_ffmpeg_exprs(
    keyframes: list["Keyframe"],
    duration: float,
    width: int,
    height: int,
    base_x_pct: float | None,
    base_y_pct: float | None,
    base_opacity: float,
    base_scale: float,
) -> dict[str, str]:
    """Build ffmpeg timeline expressions for x, y, opacity, scale from keyframes.

    Returns a dict with keys 'x', 'y', 'opacity', 'scale' — each is a string
    suitable for use in ffmpeg overlay/scale filter expressions.

    Uses piecewise linear interpolation between keyframe values. Properties not
    set in a keyframe hold their previous value. The 't' variable in expressions
    is the current timestamp in the composited video.
    """
    if not keyframes:
        return {}

    # Sort keyframes by time (spec validator requires ascending, but be safe)
    kfs = sorted(keyframes, key=lambda k: k.time)

    def _fill_property(prop: str, base_val: float | None) -> list[tuple[float, float]] | None:
        """Return [(time, value), ...] with gaps filled from previous value."""
        points: list[tuple[float, float]] = []
        last = base_val
        for kf in kfs:
            v = getattr(kf, prop, None)
            if v is not None:
                last = v
            if last is not None:
                points.append((kf.time, last))
        if not points or last is None:
            return None
        # Prepend t=0 with base value if not already there
        if points[0][0] > 0.0 and base_val is not None:
            points = [(0.0, base_val)] + points
        return points

    def _piecewise_linear(points: list[tuple[float, float]], var: str = "t") -> str:
        """Build a nested if() expression for piecewise linear interpolation."""
        if len(points) == 1:
            return str(points[0][1])

        # Work backwards: expr = if(lt(t, t_n), lerp(v_{n-1}, v_n, (t-t_{n-1})/(t_n-t_{n-1})), v_n)
        expr = str(points[-1][1])
        for i in range(len(points) - 1, 0, -1):
            t0, v0 = points[i - 1]
            t1, v1 = points[i]
            dt = t1 - t0
            if dt <= 0:
                continue
            lerp = f"({v0}+({v1}-{v0})*({var}-{t0})/{dt})"
            expr = f"if(lt({var},{t1}),{lerp},{expr})"
        return expr

    result: dict[str, str] = {}

    # x — convert pct to pixels
    x_pts = _fill_property("x_pct", base_x_pct)
    if x_pts:
        pct_expr = _piecewise_linear(x_pts)
        result["x"] = f"({pct_expr}*{width}/100)"

    # y — convert pct to pixels
    y_pts = _fill_property("y_pct", base_y_pct)
    if y_pts:
        pct_expr = _piecewise_linear(y_pts)
        result["y"] = f"({pct_expr}*{height}/100)"

    # opacity — returned as 0.0–1.0 float expression (caller applies via volume/alpha)
    op_pts = _fill_property("opacity", base_opacity)
    if op_pts:
        result["opacity"] = _piecewise_linear(op_pts)

    # scale — returned as a multiplier expression
    sc_pts = _fill_property("scale", base_scale)
    if sc_pts:
        result["scale"] = _piecewise_linear(sc_pts)

    # rotation field is present on Keyframe for forward-compatibility but
    # ffmpeg overlay expressions for rotation require a filter graph rewrite;
    # deferred to a future implementation wave.

    return result
