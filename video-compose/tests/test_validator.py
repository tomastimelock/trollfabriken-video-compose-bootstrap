"""Validator test suite — run with: python tests/test_validator.py"""
from __future__ import annotations

from video_compose.schema.validator import validate

PASS = 0
FAIL = 0


def check(label, spec, *, expect_valid=True, expect_errors=None, expect_warnings=None):
    global PASS, FAIL
    r = validate(spec)
    ok = True

    if r.is_valid != expect_valid:
        ok = False
        print(f"  is_valid={r.is_valid}, expected {expect_valid}")

    for fragment in (expect_errors or []):
        if not any(fragment in e for e in r.errors):
            ok = False
            print(f"  MISSING error containing {fragment!r}")
            print(f"  actual errors: {r.errors}")

    for fragment in (expect_warnings or []):
        if not any(fragment in w for w in r.warnings):
            ok = False
            print(f"  MISSING warning containing {fragment!r}")
            print(f"  actual warnings: {r.warnings}")

    status = "PASS" if ok else "FAIL"
    if ok:
        PASS += 1
    else:
        FAIL += 1
        for e in r.errors:
            print(f"       error: {e}")
        for w in r.warnings:
            print(f"       warn:  {w}")
    print(f"{status}  {label}")


BASE = {"tvcs": "1.0", "segments": [{"id": "x", "type": "blank", "duration": 2.0}]}

# 1. Minimal valid spec
check("minimal valid spec", BASE, expect_valid=True)

# 2. Structural — missing required field
check(
    "missing duration",
    {"tvcs": "1.0", "segments": [{"id": "x", "type": "blank"}]},
    expect_valid=False,
    expect_errors=["duration"],
)

# 3. Duplicate segment IDs (caught by Pydantic validator)
check(
    "duplicate segment IDs",
    {"tvcs": "1.0", "segments": [
        {"id": "dup", "type": "blank", "duration": 1.0},
        {"id": "dup", "type": "blank", "duration": 1.0},
    ]},
    expect_valid=False,
    expect_errors=["Duplicate"],
)

# 4. Bad $sources reference
check(
    "bad source ref",
    {
        "tvcs": "1.0",
        "data_sources": {"sales": {"type": "csv", "path": "x.csv"}},
        "segments": [{"id": "s", "type": "chart", "duration": 3.0,
                      "chart_type": "bar", "data": "$sources.missing"}],
    },
    expect_valid=False,
    expect_errors=["sources.missing"],
)

# 5. Good $sources reference
check(
    "good source ref",
    {
        "tvcs": "1.0",
        "data_sources": {"sales": {"type": "csv", "path": "x.csv"}},
        "segments": [{"id": "s", "type": "chart", "duration": 3.0,
                      "chart_type": "bar", "data": "$sources.sales"}],
    },
    expect_valid=True,
)

# 6. Transition override — unknown from
check(
    "transition override unknown from",
    {
        "tvcs": "1.0",
        "segments": [
            {"id": "a", "type": "blank", "duration": 1.0},
            {"id": "b", "type": "blank", "duration": 1.0},
        ],
        "transitions": {"overrides": [{"from": "nope", "to": "b", "type": "dissolve_ii", "duration": 0.5}]},
    },
    expect_valid=False,
    expect_errors=["'nope'"],
)

# 7. Transition override — unknown to
check(
    "transition override unknown to",
    {
        "tvcs": "1.0",
        "segments": [
            {"id": "a", "type": "blank", "duration": 1.0},
            {"id": "b", "type": "blank", "duration": 1.0},
        ],
        "transitions": {"overrides": [{"from": "a", "to": "gone", "type": "dissolve_ii", "duration": 0.5}]},
    },
    expect_valid=False,
    expect_errors=["'gone'"],
)

# 8. Valid color-fx grade slug
check(
    "valid grade slug",
    {"tvcs": "1.0", "theme": {"grade": "golden_hour_standard"},
     "segments": [{"id": "x", "type": "blank", "duration": 1.0}]},
    expect_valid=True,
)

# 9. Invalid color-fx grade slug
check(
    "invalid grade slug",
    {"tvcs": "1.0", "theme": {"grade": "golden_hour_xtra_crispy"},
     "segments": [{"id": "x", "type": "blank", "duration": 1.0}]},
    expect_valid=False,
    expect_errors=["golden_hour_xtra_crispy"],
)

# 10. Per-segment grade override — invalid
check(
    "invalid per-segment grade",
    {"tvcs": "1.0", "segments": [
        {"id": "x", "type": "blank", "duration": 1.0, "grade": "not_a_real_grade"},
    ]},
    expect_valid=False,
    expect_errors=["not_a_real_grade"],
)

# 11. Voiceover auto + no narration → warning
check(
    "voiceover auto no narration warns",
    {
        "tvcs": "1.0",
        "audio": {"voiceover": {"provider": "talk-cast", "script": "auto"}},
        "segments": [{"id": "x", "type": "blank", "duration": 2.0}],
    },
    expect_valid=True,
    expect_warnings=["voiceover"],
)

# 12. Voiceover auto WITH narration → no warning
check(
    "voiceover auto with narration ok",
    {
        "tvcs": "1.0",
        "audio": {"voiceover": {"provider": "talk-cast", "script": "auto"}},
        "segments": [{"id": "x", "type": "blank", "duration": 2.0, "narration": "Hello world"}],
    },
    expect_valid=True,
)

# 13. Empty text overlay text
check(
    "empty text overlay",
    {"tvcs": "1.0", "segments": [
        {"id": "x", "type": "blank", "duration": 2.0,
         "overlays": [{"type": "text", "text": "   "}]},
    ]},
    expect_valid=False,
    expect_errors=["empty"],
)

# 14. Audio track timing — bad segment id
check(
    "audio track bad segment timing",
    {
        "tvcs": "1.0",
        "audio": {"tracks": [{"source": "x.mp3", "timing": "no_such_segment"}]},
        "segments": [{"id": "x", "type": "blank", "duration": 2.0}],
    },
    expect_valid=False,
    expect_errors=["no_such_segment"],
)

# 15. Audio track timing — valid segment id
check(
    "audio track valid segment timing",
    {
        "tvcs": "1.0",
        "audio": {"tracks": [{"source": "x.mp3", "timing": "x"}]},
        "segments": [{"id": "x", "type": "blank", "duration": 2.0}],
    },
    expect_valid=True,
)

# 16. Voiceover manual without text (Pydantic catches it)
check(
    "voiceover manual no text",
    {
        "tvcs": "1.0",
        "audio": {"voiceover": {"provider": "talk-cast", "script": "manual"}},
        "segments": [{"id": "x", "type": "blank", "duration": 2.0}],
    },
    expect_valid=False,
    expect_errors=["text"],
)

# 17. Transition default type invalid
check(
    "invalid default transition type",
    {
        "tvcs": "1.0",
        "segments": [{"id": "x", "type": "blank", "duration": 2.0}],
        "transitions": {"default": {"type": "teleport_to_the_moon_xxxxxx", "duration": 0.5}},
    },
    expect_valid=False,
    expect_errors=["teleport_to_the_moon_xxxxxx"],
)

# 18. CSV source with neither path nor url
check(
    "csv no path or url",
    {
        "tvcs": "1.0",
        "data_sources": {"bad": {"type": "csv"}},
        "segments": [{"id": "x", "type": "blank", "duration": 1.0}],
    },
    expect_valid=False,
    expect_errors=["path"],
)

# 19. Full valid complex spec
check(
    "full valid complex spec",
    {
        "tvcs": "1.0",
        "meta": {"title": "Demo"},
        "output": {"width": 1280, "height": 720, "fps": 30, "formats": ["mp4"]},
        "theme": {"grade": "nordic_desaturation_subtle"},
        "data_sources": {"sales": {"type": "csv", "path": "./sales.csv"}},
        "audio": {
            "voiceover": {"script": "auto"},
            "tracks": [{"source": "bg.mp3", "timing": "throughout"}],
        },
        "segments": [
            {"id": "intro", "type": "mathviz", "duration": 4.0, "effect": "matrix_rain",
             "narration": "Welcome.", "grade": "cyberpunk_neon_bold",
             "overlays": [{"type": "text", "text": "Hello", "effect": "fade_in"}],
             "transition_out": {"type": "dissolve_ii", "duration": 0.5}},
            {"id": "chart", "type": "chart", "duration": 5.0,
             "chart_type": "bar", "data": "$sources.sales"},
            {"id": "outro", "type": "blank", "duration": 2.0},
        ],
        "transitions": {
            "default": {"type": "dissolve_ii", "duration": 0.5},
            "overrides": [{"from": "chart", "to": "outro", "type": "slide_left", "duration": 0.4}],
        },
    },
    expect_valid=True,
)

print(f"\n{'='*40}")
print(f"Results: {PASS} passed, {FAIL} failed")
if FAIL:
    raise SystemExit(1)
