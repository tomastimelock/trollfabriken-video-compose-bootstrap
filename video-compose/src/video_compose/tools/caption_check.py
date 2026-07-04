from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CaptionViolation:
    cue_index: int
    timestamp: str
    rule: str
    value: float
    limit: float

    def __str__(self) -> str:
        return f"Cue {self.cue_index} [{self.timestamp}]: {self.rule} ({self.value:.1f} > {self.limit})"


def check_srt(
    srt_content: str,
    max_cps: float = 17.0,
    max_chars_per_line: int = 42,
    min_display_sec: float = 1.0,
    max_lines_per_cue: int = 2,
) -> list[CaptionViolation]:
    """Check SRT content against broadcast/web caption compliance rules."""
    violations: list[CaptionViolation] = []
    blocks = re.split(r"\n\s*\n", srt_content.strip())

    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        try:
            idx = int(lines[0].strip())
        except ValueError:
            continue

        timing = lines[1].strip()
        text_lines = lines[2:]
        text = " ".join(text_lines)
        total_chars = len(text.replace(" ", ""))

        # Parse timing
        m = re.match(
            r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)",
            timing,
        )
        if not m:
            continue
        h1, m1, s1, ms1 = int(m[1]), int(m[2]), int(m[3]), int(m[4])
        h2, m2, s2, ms2 = int(m[5]), int(m[6]), int(m[7]), int(m[8])
        start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000
        end = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000
        dur = end - start

        if dur < min_display_sec:
            violations.append(CaptionViolation(idx, timing, "display_too_short_sec", dur, min_display_sec))

        if dur > 0:
            cps = total_chars / dur
            if cps > max_cps:
                violations.append(CaptionViolation(idx, timing, "cps_too_high", cps, max_cps))

        for line in text_lines:
            if len(line) > max_chars_per_line:
                violations.append(CaptionViolation(idx, timing, "line_too_long_chars", len(line), max_chars_per_line))

        if len(text_lines) > max_lines_per_cue:
            violations.append(CaptionViolation(idx, timing, "too_many_lines", len(text_lines), max_lines_per_cue))

    return violations


def check_srt_file(path: str | Path, **kwargs) -> list[CaptionViolation]:
    return check_srt(Path(path).read_text(encoding="utf-8"), **kwargs)
