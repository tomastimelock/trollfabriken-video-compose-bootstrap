"""Tests for PromptBuilder."""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from video_compose.llm import FXCatalog, PromptBuilder


def test_catalog_has_all_keys():
    pb = PromptBuilder()
    cat = pb.get_catalog()
    assert cat.mathviz_effects, "mathviz_effects should be non-empty"
    assert cat.chart_types == [
        "bar", "line", "scatter", "pie", "heatmap",
        "treemap", "sankey", "area", "radar", "bubble",
        "waterfall", "funnel", "gantt", "histogram",
    ]
    assert "constellation" in cat.shape_effects
    assert "mandelbrot" in cat.fractal_effects
    assert "ken_burns" in cat.still_motions
    assert set(cat.sources.keys()) >= {
        "mathviz_effects", "shape_effects", "chart_types",
        "fractal_effects", "geomap_views", "transition_types",
    }


def test_catalog_cached():
    pb = PromptBuilder()
    c1 = pb.get_catalog()
    c2 = pb.get_catalog()
    assert c1 is c2, "catalog should be the same object on second call"


def test_invalidate_catalog():
    pb = PromptBuilder()
    c1 = pb.get_catalog()
    pb.invalidate_catalog()
    c2 = pb.get_catalog()
    assert c1 is not c2, "invalidate should force a new catalog build"


def test_system_prompt_structure():
    pb = PromptBuilder()
    prompt = pb.build_system_prompt()
    assert "tvcs" in prompt.lower()
    assert "## Segment type reference" in prompt
    assert "## Available FX catalog" in prompt
    assert "## Full TVCS JSON Schema" in prompt
    assert len(prompt) > 5000, "system prompt should be substantial"


def test_system_prompt_contains_valid_schema():
    pb = PromptBuilder()
    prompt = pb.build_system_prompt()
    # Extract JSON from schema block
    start = prompt.index("## Full TVCS JSON Schema\n```json\n") + len("## Full TVCS JSON Schema\n```json\n")
    end = prompt.index("\n```", start)
    schema_str = prompt[start:end]
    schema = json.loads(schema_str)
    assert "$defs" in schema or "properties" in schema
    assert schema.get("title") == "TVCSSpec"


def test_user_prompt_basic():
    pb = PromptBuilder()
    prompt = pb.build_user_prompt("A 30-second intro video")
    assert "30-second intro video" in prompt
    assert "1920x1080" in prompt
    assert "raw JSON only" in prompt


def test_user_prompt_with_all_options():
    pb = PromptBuilder()
    prompt = pb.build_user_prompt(
        "Product launch",
        output_width=1280,
        output_height=720,
        fps=25,
        total_duration=45.0,
        data_context="CSV with columns: month, revenue, units",
        style_hints="dark cyberpunk neon",
    )
    assert "1280x720" in prompt
    assert "45s" in prompt
    assert "month, revenue, units" in prompt
    assert "cyberpunk neon" in prompt


def test_catalog_to_dict():
    pb = PromptBuilder()
    cat = pb.get_catalog()
    d = cat.to_dict()
    assert "mathviz_effects" in d
    assert "sources" not in d, "sources should be excluded from to_dict()"


def test_segment_types_in_prompt():
    pb = PromptBuilder()
    prompt = pb.build_system_prompt()
    for seg_type in ["blank", "mathviz", "chart", "geomap", "shape", "fractal", "still", "image", "video", "slide"]:
        assert f"| {seg_type} |" in prompt, f"segment type {seg_type!r} missing from segment table"


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {fn.__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
