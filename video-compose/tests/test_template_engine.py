"""Tests for TemplateEngine: substitution, type coercion, and error paths."""
import pytest
from video_compose.templates.engine import (
    TemplateEngine,
    TemplateFillError,
    TemplateTypeError,
    MissingVariable,
)

engine = TemplateEngine()


def _tmpl(**vars_defaults) -> dict:
    """Minimal template dict with a string overlay and the given variables."""
    return {
        "template": {
            "variables": [
                {"name": k, "type": "string", "required": True, "default": v}
                for k, v in vars_defaults.items()
            ]
        },
        "output": {"path": "out.mp4"},
        "segments": [
            {
                "id": "s1",
                "type": "blank",
                "duration": 2.0,
                "color": "{{bg_color}}" if "bg_color" in vars_defaults else "#000000",
                "overlays": [],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Whole-slot substitution (typed value replacement)
# ---------------------------------------------------------------------------

class TestWholeSlotSubstitution:
    def test_string_var_replaced(self):
        tmpl = {
            "template": {"variables": [{"name": "title", "type": "string", "required": True}]},
            "segments": [{"type": "blank", "duration": 2.0, "overlays": [
                {"type": "text", "text": "{{title}}"}
            ]}],
        }
        result = engine.fill(tmpl, {"title": "Hello"})
        assert result["segments"][0]["overlays"][0]["text"] == "Hello"

    def test_number_var_coerced_to_float(self):
        tmpl = {
            "template": {"variables": [{"name": "dur", "type": "number", "required": True}]},
            "segments": [{"type": "blank", "duration": "{{dur}}", "overlays": []}],
        }
        result = engine.fill(tmpl, {"dur": "3.5"})
        assert result["segments"][0]["duration"] == 3.5
        assert isinstance(result["segments"][0]["duration"], float)

    def test_duration_var_coerced_to_float(self):
        tmpl = {
            "template": {"variables": [{"name": "d", "type": "duration", "required": True}]},
            "segments": [{"type": "blank", "duration": "{{d}}", "overlays": []}],
        }
        result = engine.fill(tmpl, {"d": 10})
        assert result["segments"][0]["duration"] == 10.0

    def test_boolean_var_coerced_to_bool(self):
        tmpl = {
            "template": {"variables": [{"name": "flag", "type": "boolean", "required": True}]},
            "segments": [{"type": "still", "duration": 1.0, "loop": "{{flag}}", "overlays": []}],
        }
        result = engine.fill(tmpl, {"flag": "true"})
        assert result["segments"][0]["loop"] is True

    def test_boolean_false_string(self):
        tmpl = {
            "template": {"variables": [{"name": "f", "type": "boolean", "required": False, "default": True}]},
            "segments": [{"type": "still", "loop": "{{f}}", "overlays": []}],
        }
        result = engine.fill(tmpl, {"f": "false"})
        assert result["segments"][0]["loop"] is False

    def test_color_passes_through_as_string(self):
        tmpl = {
            "template": {"variables": [{"name": "bg", "type": "color", "required": True}]},
            "segments": [{"type": "blank", "color": "{{bg}}", "overlays": []}],
        }
        result = engine.fill(tmpl, {"bg": "#ff0000"})
        assert result["segments"][0]["color"] == "#ff0000"


# ---------------------------------------------------------------------------
# Partial slot substitution (always string)
# ---------------------------------------------------------------------------

class TestPartialSlotSubstitution:
    def test_partial_text_substitution(self):
        tmpl = {
            "template": {"variables": [{"name": "name", "type": "string", "required": True}]},
            "segments": [{"type": "blank", "overlays": [
                {"type": "text", "text": "Hello, {{name}}!"}
            ]}],
        }
        result = engine.fill(tmpl, {"name": "World"})
        assert result["segments"][0]["overlays"][0]["text"] == "Hello, World!"

    def test_multiple_slots_in_one_string(self):
        tmpl = {
            "template": {"variables": [
                {"name": "a", "type": "string", "required": True},
                {"name": "b", "type": "string", "required": True},
            ]},
            "segments": [{"type": "blank", "overlays": [
                {"type": "text", "text": "{{a}} — {{b}}"}
            ]}],
        }
        result = engine.fill(tmpl, {"a": "Foo", "b": "Bar"})
        assert result["segments"][0]["overlays"][0]["text"] == "Foo — Bar"


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------

class TestDefaultValues:
    def test_default_used_when_var_not_provided(self):
        tmpl = {
            "template": {"variables": [
                {"name": "title", "type": "string", "required": False, "default": "Untitled"}
            ]},
            "segments": [{"type": "blank", "overlays": [
                {"type": "text", "text": "{{title}}"}
            ]}],
        }
        result = engine.fill(tmpl, {})
        assert result["segments"][0]["overlays"][0]["text"] == "Untitled"

    def test_explicit_value_overrides_default(self):
        tmpl = {
            "template": {"variables": [
                {"name": "title", "type": "string", "required": False, "default": "Untitled"}
            ]},
            "segments": [{"type": "blank", "overlays": [
                {"type": "text", "text": "{{title}}"}
            ]}],
        }
        result = engine.fill(tmpl, {"title": "My Title"})
        assert result["segments"][0]["overlays"][0]["text"] == "My Title"

    def test_dict_default_for_data_ref(self):
        tmpl = {
            "template": {"variables": [
                {"name": "data", "type": "data_ref", "required": True,
                 "default": {"A": 1.0, "B": 2.0}}
            ]},
            "segments": [{"type": "chart", "data": "{{data}}", "overlays": []}],
        }
        result = engine.fill(tmpl, {})
        assert result["segments"][0]["data"] == {"A": 1.0, "B": 2.0}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_missing_required_raises(self):
        tmpl = {
            "template": {"variables": [
                {"name": "title", "type": "string", "required": True}
            ]},
            "segments": [{"type": "blank", "overlays": [
                {"type": "text", "text": "{{title}}"}
            ]}],
        }
        with pytest.raises(TemplateFillError) as exc_info:
            engine.fill(tmpl, {})
        assert any(v.name == "title" for v in exc_info.value.missing)

    def test_invalid_number_raises_type_error(self):
        tmpl = {
            "template": {"variables": [
                {"name": "dur", "type": "number", "required": True}
            ]},
            "segments": [{"type": "blank", "duration": "{{dur}}", "overlays": []}],
        }
        with pytest.raises(TemplateTypeError):
            engine.fill(tmpl, {"dur": "not_a_number"})

    def test_unknown_slot_left_as_is(self):
        """Slots with no matching variable are left verbatim (no crash)."""
        tmpl = {
            "template": {"variables": []},
            "segments": [{"type": "blank", "overlays": [
                {"type": "text", "text": "{{unknown_var}}"}
            ]}],
        }
        result = engine.fill(tmpl, {})
        assert result["segments"][0]["overlays"][0]["text"] == "{{unknown_var}}"


# ---------------------------------------------------------------------------
# list_unfilled
# ---------------------------------------------------------------------------

class TestListUnfilled:
    def test_reports_unfilled_required(self):
        tmpl = {
            "template": {"variables": [
                {"name": "img", "type": "image_path", "required": True},
                {"name": "title", "type": "string", "required": False, "default": "x"},
            ]},
            "segments": [],
        }
        missing = engine.list_unfilled(tmpl, variables={})
        names = [m.name for m in missing]
        assert "img" in names
        assert "title" not in names

    def test_no_missing_when_all_provided(self):
        tmpl = {
            "template": {"variables": [
                {"name": "img", "type": "image_path", "required": True},
            ]},
            "segments": [],
        }
        missing = engine.list_unfilled(tmpl, variables={"img": "/path/to/img.jpg"})
        assert missing == []
