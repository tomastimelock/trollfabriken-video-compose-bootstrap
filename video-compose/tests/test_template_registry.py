"""Tests for TemplateRegistry: bundled templates, listing, filtering, previews."""
import json
import pytest
from pathlib import Path
from video_compose.templates.registry import TemplateRegistry, TemplateInfo

registry = TemplateRegistry()


class TestListAll:
    def test_list_returns_nonempty(self):
        items = registry.list()
        assert len(items) >= 26, f"Expected >=26 bundled templates, got {len(items)}"

    def test_all_items_are_template_info(self):
        for item in registry.list():
            assert isinstance(item, TemplateInfo)

    def test_all_have_required_fields(self):
        for item in registry.list():
            assert item.id, f"Missing id on {item}"
            assert item.name, f"Missing name on {item}"
            assert item.category, f"Missing category on {item}"


class TestFilterByCategory:
    def test_filter_social(self):
        items = registry.list(category="social")
        assert len(items) >= 4
        assert all(i.category == "social" for i in items)

    def test_filter_swedish(self):
        items = registry.list(category="swedish")
        assert len(items) >= 3
        assert all(i.category == "swedish" for i in items)

    def test_unknown_category_returns_empty(self):
        items = registry.list(category="does_not_exist")
        assert items == []


class TestFilterByTags:
    def test_filter_by_single_tag(self):
        items = registry.list(tags=["news"])
        assert len(items) >= 1
        assert all("news" in i.tags for i in items)

    def test_filter_by_multiple_tags_is_union(self):
        social = registry.list(tags=["social"])
        chart = registry.list(tags=["chart"])
        combined = registry.list(tags=["social", "chart"])
        social_ids = {t.id for t in social}
        chart_ids = {t.id for t in chart}
        combined_ids = {t.id for t in combined}
        # combined must be a superset of both individual results
        assert social_ids.issubset(combined_ids)
        assert chart_ids.issubset(combined_ids)
        # combined cannot exceed the union
        assert combined_ids == social_ids | chart_ids


class TestSearchQuery:
    def test_search_finds_election(self):
        items = registry.list(search_query="election")
        ids = [i.id for i in items]
        assert "swedish_election_map" in ids

    def test_search_finds_podcast(self):
        items = registry.list(search_query="podcast")
        ids = [i.id for i in items]
        assert "audiogram_podcast" in ids

    def test_search_no_match_returns_empty(self):
        items = registry.list(search_query="zzznomatch999zzz")
        assert items == []


class TestGet:
    def test_get_returns_full_dict(self):
        raw = registry.get("social_quote_card")
        assert isinstance(raw, dict)
        assert raw.get("tvcs") == "1.0"
        assert "segments" in raw

    def test_get_nonexistent_raises(self):
        with pytest.raises(KeyError):
            registry.get("does_not_exist_template")

    def test_get_info_returns_template_info(self):
        info = registry.get_info("product_launch_dark")
        assert isinstance(info, TemplateInfo)
        assert info.id == "product_launch_dark"
        assert info.category == "product_launch"


class TestCategories:
    def test_categories_nonempty(self):
        cats = registry.categories()
        assert len(cats) >= 10

    def test_known_categories_present(self):
        cats = registry.categories()
        for expected in ("social", "swedish", "financial", "event", "people", "audio"):
            assert expected in cats, f"Category '{expected}' missing from {cats}"


class TestCompactCatalog:
    def test_catalog_length_matches_list(self):
        catalog = registry.compact_catalog()
        all_items = registry.list()
        assert len(catalog) == len(all_items)

    def test_catalog_entries_have_required_keys(self):
        for entry in registry.compact_catalog():
            assert "id" in entry
            assert "name" in entry
            assert "category" in entry
            assert "description" in entry


class TestPreviews:
    def test_thumbnail_exists_for_all_bundled(self):
        for info in registry.list():
            path = registry.get_preview_path(info.id, size="thumbnail")
            assert path is not None and path.exists(), (
                f"Missing thumbnail for {info.id}: {path}"
            )

    def test_full_preview_exists_for_all_bundled(self):
        for info in registry.list():
            path = registry.get_preview_path(info.id, size="full")
            assert path is not None and path.exists(), (
                f"Missing full preview for {info.id}: {path}"
            )

    def test_unknown_template_preview_returns_none(self):
        path = registry.get_preview_path("does_not_exist", size="thumbnail")
        assert path is None


class TestUserPrefixEnforcement:
    def test_user_templates_require_user_prefix(self, tmp_path):
        """A JSON placed in user dir without 'user.' prefix is rejected."""
        (tmp_path / "naughty_template.json").write_text(
            json.dumps({
                "tvcs": "1.0",
                "template": {"id": "naughty_template", "name": "Bad", "category": "social",
                             "tags": [], "description": "", "variables": []},
                "segments": [],
            }),
            encoding="utf-8",
        )
        reg = TemplateRegistry(extra_dirs=[tmp_path])
        # Should not appear in list (or raise) — invalid user template
        items = reg.list()
        ids = [i.id for i in items]
        assert "naughty_template" not in ids

    def test_user_templates_with_prefix_are_loaded(self, tmp_path):
        """A JSON placed in user dir with 'user.' prefix is loaded."""
        (tmp_path / "user.my_custom.json").write_text(
            json.dumps({
                "tvcs": "1.0",
                "template": {"id": "user.my_custom", "name": "My Custom", "category": "social",
                             "tags": [], "description": "A user template", "variables": []},
                "segments": [],
            }),
            encoding="utf-8",
        )
        reg = TemplateRegistry(extra_dirs=[tmp_path])
        ids = [i.id for i in reg.list()]
        assert "user.my_custom" in ids


class TestRequiredVariables:
    def test_required_variables_subset_of_all_variables(self):
        info = registry.get_info("product_launch_dark")
        req = info.required_variables()
        all_vars = info.variables
        req_names = {v["name"] for v in req}
        all_names = {v["name"] for v in all_vars}
        assert req_names.issubset(all_names)

    def test_image_path_is_required_in_product_launch(self):
        info = registry.get_info("product_launch_dark")
        req_names = [v["name"] for v in info.required_variables()]
        assert "product_image" in req_names
