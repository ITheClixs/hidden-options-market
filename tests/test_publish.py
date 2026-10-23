"""Publishing tests.

Every number in the paper and README is rendered from the small JSON files in
`results/`, and CI re-renders them to catch a hand edit or a stale file. These tests pin
the properties that make that safe: a result file is byte-stable, a macro name can never
produce invalid or colliding LaTeX, and an edited output is always reported as drift.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from hidden_options import cli
from hidden_options.config import PROJECT_ROOT
from hidden_options.publish import (
    Column,
    Result,
    check_drift,
    now_iso,
    publish,
    read_results,
    registry,
    render_macros,
    render_readme,
    render_table,
    write_result,
)

TEMPLATE = "# Title\n\nOpen interest reached {{OiEnd}} contracts, worth {{MarkEnd}}.\n"


def make_result(name: str = "panel", **overrides) -> Result:
    fields = {
        "name": name,
        "values": {"oi_end": 73.0, "dates": [1, 2]},
        "macros": {"OiEnd": "73.0", "MarkEnd": r"\$596bn"},
        "inputs": {"first_date": "2025-07-23", "last_date": "2026-08-17"},
        "generated_at": "2026-10-23T12:00:00+00:00",
    }
    return Result(**{**fields, **overrides})


def make_project(root: Path, *results: Result, template: str = TEMPLATE) -> Path:
    """A minimal project tree: a README template and the given result files."""
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "readme.template.md").write_text(template)
    (root / "paper" / "tables").mkdir(parents=True)
    for result in results:
        write_result(result, root / "results")
    return root


TABLE_MODULE = """\
from hidden_options.publish import Column, registry, render_table


@registry.TABLES.register("oi")
def oi_table(results):
    rows = [{"oi": results["panel"].values["oi_end"]}]
    return render_table(rows, [Column("oi", "OI", ".1f")], caption="c", label="tab:oi")
"""


@pytest.fixture
def registered_oi_table(tmp_path_factory, monkeypatch):
    """A registration module that puts one table into an otherwise empty registry.

    Nothing has imported the module when a test starts, which is the state of a fresh
    process that calls the library without going through the CLI.
    """
    module_dir = tmp_path_factory.mktemp("registrations")
    (module_dir / "oi_table_registration.py").write_text(TABLE_MODULE)
    monkeypatch.syspath_prepend(str(module_dir))
    monkeypatch.setattr(registry, "TABLES", registry.Registry("table"))
    monkeypatch.setattr(registry, "REGISTRATION_MODULES", ("oi_table_registration",))
    sys.modules.pop("oi_table_registration", None)
    yield "oi_table_registration"
    sys.modules.pop("oi_table_registration", None)


class TestResults:
    def test_result_roundtrip_is_byte_stable(self, tmp_path):
        result = make_result()
        path = write_result(result, tmp_path)
        first = path.read_bytes()

        assert write_result(result, tmp_path) == path
        assert path.read_bytes() == first
        assert read_results(tmp_path) == {"panel": result}

    def test_file_has_sorted_keys_indent_two_and_trailing_newline(self, tmp_path):
        text = write_result(make_result(), tmp_path).read_text()

        assert text.endswith("}\n")
        assert list(json.loads(text)) == sorted(json.loads(text))
        assert '\n  "generated_at"' in text

    def test_rerun_with_new_timestamp_leaves_unchanged_result_alone(self, tmp_path):
        path = write_result(make_result(generated_at="2026-10-23T12:00:00+00:00"), tmp_path)
        before = path.read_bytes()

        write_result(make_result(generated_at="2026-11-01T09:30:00+00:00"), tmp_path)

        assert path.read_bytes() == before

    def test_changed_content_is_rewritten_with_its_new_timestamp(self, tmp_path):
        write_result(make_result(), tmp_path)

        write_result(
            make_result(macros={"OiEnd": "74.1"}, generated_at="2026-11-01T09:30:00+00:00"),
            tmp_path,
        )

        stored = read_results(tmp_path)["panel"]
        assert stored.macros == {"OiEnd": "74.1"}
        assert stored.generated_at == "2026-11-01T09:30:00+00:00"

    @pytest.mark.parametrize("name", ["../escape", "a/b", "", "has space", "dot.json"])
    def test_result_name_must_be_a_safe_file_stem(self, tmp_path, name):
        with pytest.raises(ValueError, match="name"):
            write_result(make_result(name=name), tmp_path)

    def test_unreadable_stored_file_is_overwritten(self, tmp_path):
        (tmp_path / "panel.json").write_text("{not json")

        write_result(make_result(), tmp_path)

        assert read_results(tmp_path) == {"panel": make_result()}

    def test_numpy_numbers_are_written_as_plain_json_numbers(self, tmp_path):
        values = {
            "count": np.int64(3),
            "beta": np.float32(0.5),
            "significant": np.bool_(True),
            "mean": np.float64(1.5),
            "series": [np.int32(1), np.float64(2.5)],
            "nested": {"rank": np.uint8(7)},
        }
        result = make_result(values=values)

        stored = json.loads(write_result(result, tmp_path).read_text())["values"]

        assert stored == {
            "count": 3,
            "beta": 0.5,
            "significant": True,
            "mean": 1.5,
            "series": [1, 2.5],
            "nested": {"rank": 7},
        }
        assert [type(stored[k]) for k in ("count", "significant")] == [int, bool]

    def test_rewriting_numpy_values_is_byte_stable(self, tmp_path):
        result = make_result(values={"count": np.int64(3), "beta": np.float32(0.5)})
        path = write_result(result, tmp_path)
        first = path.read_bytes()

        later = make_result(values=result.values, generated_at="2026-11-01T09:30:00+00:00")
        write_result(later, tmp_path)

        assert path.read_bytes() == first

    @pytest.mark.parametrize(
        "field, value, where",
        [
            ("values", {"when": datetime(2026, 8, 17)}, "when"),
            ("values", {"weights": np.array([1.0, 2.0])}, "weights"),
            ("values", {"deep": {"inner": [1, {2, 3}]}}, "inner"),
            ("values", {"beta": float("nan")}, "beta"),
            ("values", {"beta": np.float32("inf")}, "beta"),
            ("values", {"root": 1 + 2j}, "root"),
            ("values", {"anything": object()}, "anything"),
            ("inputs", {"first_date": date(2025, 7, 23)}, "first_date"),
        ],
    )
    def test_unserialisable_value_names_the_result_and_the_key(self, tmp_path, field, value, where):
        with pytest.raises(ValueError, match=rf"'panel'.*{field}.*{where}"):
            write_result(make_result(**{field: value}), tmp_path)

        assert not (tmp_path / "panel.json").exists()

    def test_unserialisable_key_is_named(self, tmp_path):
        with pytest.raises(ValueError, match=r"'panel'.*values\[\(1, 2\)\]"):
            write_result(make_result(values={(1, 2): "pair"}), tmp_path)

    def test_error_without_a_single_culprit_still_names_the_result(self, tmp_path):
        """Keys of different types cannot be sorted, though each is fine on its own."""
        with pytest.raises(ValueError, match="'panel' cannot be written as JSON: "):
            write_result(make_result(values={1: "a", "b": 2}), tmp_path)

    def test_now_iso_is_a_utc_timestamp_to_the_second(self):
        stamp = datetime.fromisoformat(now_iso())

        assert stamp.utcoffset() == timedelta(0)
        assert stamp.microsecond == 0

    def test_missing_directory_means_no_results(self, tmp_path):
        assert read_results(tmp_path / "absent") == {}

    def test_only_json_files_are_results(self, tmp_path):
        write_result(make_result(), tmp_path)
        (tmp_path / ".gitkeep").write_text("")

        assert list(read_results(tmp_path)) == ["panel"]

    def test_filename_must_match_the_result_name(self, tmp_path):
        write_result(make_result(), tmp_path)
        (tmp_path / "panel.json").rename(tmp_path / "other.json")

        with pytest.raises(ValueError, match="other.json"):
            read_results(tmp_path)

    def test_malformed_file_is_named_in_the_error(self, tmp_path):
        (tmp_path / "broken.json").write_text("{not json")

        with pytest.raises(ValueError, match="broken.json"):
            read_results(tmp_path)

    def test_file_missing_a_field_is_named_in_the_error(self, tmp_path):
        (tmp_path / "thin.json").write_text(json.dumps({"name": "thin"}))

        with pytest.raises(ValueError, match="thin.json"):
            read_results(tmp_path)


class TestMacros:
    def test_macro_names_must_be_letters(self):
        for bad in ("Panel2", "oi_end", "", "Oi-End", "Oi End"):
            with pytest.raises(ValueError, match="macro"):
                render_macros({"p": make_result("p", macros={bad: "1"})})

    def test_duplicate_macro_across_results_raises(self):
        a = make_result("a", macros={"Shared": "1"})
        b = make_result("b", macros={"Shared": "2"})

        with pytest.raises(ValueError, match="Shared"):
            render_macros({"a": a, "b": b})

    @pytest.mark.parametrize(
        "value, reason",
        [
            ("two\nlines", "single-line"),
            ("unbalanced}", "unbalanced"),
            ("{open", "unbalanced"),
            ("{\\}", "unbalanced"),
            ("100%", "unescaped %"),
            ("a\\\\%", "unescaped %"),
            ("item #1", "unescaped #"),
            ("ends with \\", "trailing backslash"),
            ("\\\\\\", "trailing backslash"),
        ],
    )
    def test_value_that_would_break_the_macro_is_rejected(self, value, reason):
        with pytest.raises(ValueError, match=rf"Bad.*{reason}"):
            render_macros({"p": make_result("p", macros={"Bad": value})})

    @pytest.mark.parametrize(
        "value",
        [r"\}", r"\{", r"50\%", r"item \#1", r"\$596bn", r"line\\", r"{kept}", "-0.5", ""],
    )
    def test_escaped_characters_and_balanced_braces_are_accepted(self, value):
        text = render_macros({"p": make_result("p", macros={"Ok": value})})

        assert text.endswith(f"\\newcommand{{\\Ok}}{{{value}}}\n")

    def test_lines_are_sorted_by_name_across_results(self):
        a = make_result("a", macros={"Zeta": "1"})
        b = make_result("b", macros={"Alpha": r"\$596bn"})

        lines = [ln for ln in render_macros({"a": a, "b": b}).splitlines() if ln[0] != "%"]

        assert lines == [r"\newcommand{\Alpha}{\$596bn}", r"\newcommand{\Zeta}{1}"]

    def test_no_results_leaves_only_a_comment_header(self):
        text = render_macros({})

        assert text.endswith("\n")
        assert all(line.startswith("%") for line in text.splitlines())


class TestTable:
    COLUMNS = (
        Column("predictor", "Predictor", "s", "l"),
        Column("beta", r"$\beta$", "${:.5f}$"),
        Column("mde", "MDE80", ".5f"),
    )
    ROWS = ({"predictor": "Inventory innovation", "beta": -0.0003, "mde": 0.00062},)

    def render(self, **kwargs) -> str:
        defaults = {"caption": "Predictive regressions.", "label": "tab:pred"}
        return render_table(self.ROWS, self.COLUMNS, **{**defaults, **kwargs})

    def test_render_table_uses_booktabs_and_formats(self):
        text = self.render()

        for part in (r"\toprule", r"\midrule", r"\bottomrule", r"\begin{tabular}{lrr}"):
            assert part in text
        assert "Inventory innovation & $-0.00030$ & 0.00062 \\\\" in text
        assert r"\caption{Predictive regressions.}" in text
        assert r"\label{tab:pred}" in text

    def test_header_row_comes_from_the_columns(self):
        assert r"Predictor & $\beta$ & MDE80 \\" in self.render()

    def test_notes_are_optional_and_follow_the_table(self):
        assert "footnotesize" not in self.render()

        text = self.render(notes="Standard errors clustered by underlying.")
        assert text.index(r"\end{tabular}") < text.index("Standard errors clustered")

    def test_missing_value_prints_a_dash(self):
        rows = ({"predictor": "x", "beta": None, "mde": 1.0},)

        assert "x & -- & 1.00000" in render_table(rows, self.COLUMNS, caption="c", label="l")

    def test_missing_key_names_the_column(self):
        with pytest.raises(KeyError, match="beta"):
            render_table(({"predictor": "x", "mde": 1.0},), self.COLUMNS, caption="c", label="l")

    def test_a_table_needs_columns(self):
        with pytest.raises(ValueError, match="column"):
            render_table((), (), caption="c", label="l")

    def test_output_is_deterministic(self):
        assert self.render() == self.render()


class TestReadme:
    def test_placeholders_are_replaced(self):
        macros = {"OiEnd": "73.0", "MarkEnd": r"\$596bn"}

        assert render_readme(TEMPLATE, macros) == (
            "# Title\n\nOpen interest reached 73.0 contracts, worth \\$596bn.\n"
        )

    def test_readme_unknown_placeholder_raises(self):
        with pytest.raises(KeyError, match="Missing"):
            render_readme("value: {{Missing}}", {"OiEnd": "1"})

    def test_text_without_placeholders_is_returned_byte_for_byte(self):
        text = "A | table |\n|---:|\n\\$596bn, {braces}, and 42%\n"

        assert render_readme(text, {}) == text

    def test_unused_macros_are_fine(self):
        assert render_readme("plain", {"Unused": "1"}) == "plain"


class TestDrift:
    def test_fresh_publish_has_no_drift(self, tmp_path):
        make_project(tmp_path, make_result())

        publish(tmp_path)

        assert check_drift(tmp_path) == []
        assert (tmp_path / "README.md").read_text().startswith("# Title")

    def test_check_drift_reports_edited_readme(self, tmp_path):
        make_project(tmp_path, make_result())
        publish(tmp_path)

        (tmp_path / "README.md").write_text("hand edited\n")

        assert check_drift(tmp_path) == ["README.md"]

    def test_edited_numbers_file_is_reported(self, tmp_path):
        make_project(tmp_path, make_result())
        publish(tmp_path)

        numbers = tmp_path / "paper" / "numbers.tex"
        numbers.write_text(numbers.read_text() + r"\newcommand{\Sneaky}{1}" + "\n")

        assert check_drift(tmp_path) == ["paper/numbers.tex"]

    def test_outputs_that_were_never_published_are_reported(self, tmp_path):
        make_project(tmp_path, make_result())

        assert check_drift(tmp_path) == ["README.md", "paper/numbers.tex"]

    def test_changed_result_without_republishing_is_reported(self, tmp_path):
        make_project(tmp_path, make_result())
        publish(tmp_path)

        write_result(make_result(macros={"OiEnd": "74.1", "MarkEnd": "1"}), tmp_path / "results")

        assert check_drift(tmp_path) == ["README.md", "paper/numbers.tex"]

    def test_publish_reports_only_the_files_it_changed(self, tmp_path):
        make_project(tmp_path, make_result())

        assert publish(tmp_path) == ["README.md", "paper/numbers.tex"]
        assert publish(tmp_path) == []

    def test_registered_tables_are_rendered_and_checked(self, tmp_path):
        make_project(tmp_path, make_result())
        tables = registry.Registry("table")

        @tables.register("oi")
        def oi_table(results):
            rows = [{"oi": results["panel"].values["oi_end"]}]
            return render_table(rows, [Column("oi", "OI", ".1f")], caption="c", label="tab:oi")

        publish(tmp_path, tables=tables)
        table = tmp_path / "paper" / "tables" / "oi.tex"
        assert "73.0" in table.read_text()
        assert check_drift(tmp_path, tables=tables) == []

        table.write_text("edited\n")
        assert check_drift(tmp_path, tables=tables) == ["paper/tables/oi.tex"]

    def test_table_without_a_spec_is_stale_and_removed_by_publish(self, tmp_path):
        make_project(tmp_path, make_result())
        publish(tmp_path)
        (tmp_path / "paper" / "tables" / ".gitkeep").write_text("")
        stale = tmp_path / "paper" / "tables" / "old.tex"
        stale.write_text("left over\n")

        assert check_drift(tmp_path) == ["paper/tables/old.tex"]
        assert publish(tmp_path) == ["paper/tables/old.tex"]
        assert not stale.exists()
        assert (tmp_path / "paper" / "tables" / ".gitkeep").exists()

    def test_publish_sees_registered_tables_without_the_cli(self, tmp_path, registered_oi_table):
        make_project(tmp_path, make_result())

        assert publish(tmp_path) == ["README.md", "paper/numbers.tex", "paper/tables/oi.tex"]
        assert "73.0" in (tmp_path / "paper" / "tables" / "oi.tex").read_text()

    def test_check_drift_sees_registered_tables_without_the_cli(
        self, tmp_path, registered_oi_table
    ):
        make_project(tmp_path, make_result())

        assert check_drift(tmp_path) == ["README.md", "paper/numbers.tex", "paper/tables/oi.tex"]

    def test_committed_table_survives_publishing_from_a_fresh_process(
        self, tmp_path, monkeypatch, registered_oi_table
    ):
        make_project(tmp_path, make_result())
        publish(tmp_path)
        sys.modules.pop(registered_oi_table)
        monkeypatch.setattr(registry, "TABLES", registry.Registry("table"))

        assert publish(tmp_path) == []
        assert (tmp_path / "paper" / "tables" / "oi.tex").is_file()

    def test_explicit_tables_are_used_as_given(self, tmp_path, registered_oi_table):
        make_project(tmp_path, make_result())

        assert publish(tmp_path, tables=registry.Registry("table")) == [
            "README.md",
            "paper/numbers.tex",
        ]
        assert "oi_table_registration" not in sys.modules

    def test_missing_template_is_an_error(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="readme.template.md"):
            check_drift(tmp_path)

    def test_committed_outputs_match_the_committed_results(self):
        """The check CI runs, on this very repository."""
        assert check_drift(PROJECT_ROOT) == []


class TestRegistry:
    def test_decorator_registers_and_returns_the_function(self):
        analyses = registry.Registry("analysis")

        @analyses.register("panel")
        def panel():
            return make_result()

        assert panel().name == "panel"
        assert list(analyses.select(None)) == ["panel"]

    def test_duplicate_registration_raises(self):
        analyses = registry.Registry("analysis")
        analyses.register("panel")(lambda: make_result())

        with pytest.raises(ValueError, match="panel"):
            analyses.register("panel")(lambda: make_result())

    def test_load_registrations_imports_the_listed_modules(self, tmp_path, monkeypatch):
        (tmp_path / "fake_analysis.py").write_text(
            "from hidden_options.publish import registry\n"
            "registry.ANALYSES.register('fake')(lambda: None)\n"
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setattr(registry, "ANALYSES", registry.Registry("analysis"))
        monkeypatch.setattr(registry, "REGISTRATION_MODULES", ("fake_analysis",))

        registry.load_registrations()

        assert list(registry.ANALYSES.select()) == ["fake"]

    def test_select_one_and_unknown(self):
        analyses = registry.Registry("analysis")
        analyses.register("a")(lambda: make_result("a"))
        analyses.register("b")(lambda: make_result("b"))

        assert list(analyses.select("b")) == ["b"]
        with pytest.raises(ValueError, match="registered: a, b"):
            analyses.select("c")


@pytest.fixture
def empty_registries(monkeypatch):
    for attr, kind in (("ANALYSES", "analysis"), ("FIGURES", "figure"), ("TABLES", "table")):
        monkeypatch.setattr(registry, attr, registry.Registry(kind))


class TestCli:
    def test_results_with_nothing_registered_succeeds(self, empty_registries, tmp_path, capsys):
        assert cli.main(["results", "--root", str(tmp_path)]) == 0
        assert "no analyses" in capsys.readouterr().out.lower()
        assert not (tmp_path / "results").exists()

    def test_figures_with_nothing_registered_succeeds(self, empty_registries, capsys):
        assert cli.main(["figures"]) == 0
        assert "no figure builders" in capsys.readouterr().out.lower()

    def test_results_runs_registered_analyses_and_writes_them(self, empty_registries, tmp_path):
        registry.ANALYSES.register("panel")(lambda: make_result())
        registry.ANALYSES.register("other")(lambda: make_result("other", macros={"Other": "1"}))

        assert cli.main(["results", "--root", str(tmp_path), "--only", "panel"]) == 0

        assert sorted(read_results(tmp_path / "results")) == ["panel"]

    def test_results_without_only_runs_everything(self, empty_registries, tmp_path):
        registry.ANALYSES.register("panel")(lambda: make_result())
        registry.ANALYSES.register("other")(lambda: make_result("other", macros={"Other": "1"}))

        assert cli.main(["results", "--root", str(tmp_path)]) == 0

        assert sorted(read_results(tmp_path / "results")) == ["other", "panel"]

    def test_unknown_analysis_is_a_usage_error(self, empty_registries, tmp_path, capsys):
        assert cli.main(["results", "--root", str(tmp_path), "--only", "nope"]) == 2
        assert "nope" in capsys.readouterr().err

    def test_analysis_must_return_a_result_named_after_its_registration(
        self, empty_registries, tmp_path, capsys
    ):
        registry.ANALYSES.register("panel")(lambda: make_result("different"))

        assert cli.main(["results", "--root", str(tmp_path)]) == 2
        assert "different" in capsys.readouterr().err

    def test_figures_runs_the_registered_builders(self, empty_registries):
        built: list[str] = []
        registry.FIGURES.register("growth")(lambda: built.append("growth"))
        registry.FIGURES.register("placebo")(lambda: built.append("placebo"))

        assert cli.main(["figures", "--only", "placebo"]) == 0
        assert built == ["placebo"]

    def test_publish_then_check_passes(self, empty_registries, tmp_path):
        make_project(tmp_path, make_result())
        root = ["--root", str(tmp_path)]

        assert cli.main(["publish", *root]) == 0
        assert cli.main(["check", *root]) == 0

    def test_publish_and_check_include_registered_tables(self, tmp_path, registered_oi_table):
        make_project(tmp_path, make_result())
        root = ["--root", str(tmp_path)]

        assert cli.main(["publish", *root]) == 0
        assert (tmp_path / "paper" / "tables" / "oi.tex").is_file()
        assert cli.main(["check", *root]) == 0

    def test_check_exits_one_and_lists_drifted_paths(self, empty_registries, tmp_path, capsys):
        make_project(tmp_path, make_result())
        root = ["--root", str(tmp_path)]
        cli.main(["publish", *root])
        (tmp_path / "README.md").write_text("hand edited\n")
        capsys.readouterr()

        assert cli.main(["check", *root]) == 1
        assert "README.md" in capsys.readouterr().err

    def test_publish_without_a_template_is_a_usage_error(self, empty_registries, tmp_path, capsys):
        assert cli.main(["publish", "--root", str(tmp_path)]) == 2
        assert "readme.template.md" in capsys.readouterr().err
