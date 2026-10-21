"""Tests for the Implementation value object."""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

from algorithm_playground.core._support import split_command_text, validate_implementations
from algorithm_playground.core.implementation import Implementation


class TestConstruction:
    def test_defaults(self) -> None:
        implementation = Implementation(name="sorter", command=("./sorter",))
        assert implementation.working_directory is None
        assert implementation.build_command is None
        assert implementation.inherit_environment is False
        assert implementation.environment == {}
        assert implementation.timeout_seconds is None

    def test_is_frozen(self) -> None:
        implementation = Implementation(name="sorter", command=("./sorter",))
        with pytest.raises(dataclasses.FrozenInstanceError):
            implementation.__setattr__("name", "other")

    def test_rejects_empty_name(self) -> None:
        with pytest.raises(ValueError, match="non-empty name"):
            Implementation(name="", command=("./sorter",))

    def test_rejects_empty_command(self) -> None:
        with pytest.raises(ValueError, match="non-empty command"):
            Implementation(name="sorter", command=())

    def test_rejects_empty_build_command(self) -> None:
        with pytest.raises(ValueError, match="empty build command"):
            Implementation(name="sorter", command=("./sorter",), build_command=())

    @pytest.mark.parametrize("variable", ["", "A=B", "BAD\0NAME"])
    def test_rejects_an_invalid_environment_variable_name(self, variable: str) -> None:
        with pytest.raises(ValueError, match="invalid environment variable"):
            Implementation(name="sorter", command=("./sorter",), environment={variable: "x"})

    @pytest.mark.parametrize("timeout", [0.0, -2.0, float("nan"), float("inf")])
    def test_rejects_a_timeout_that_is_not_finite_and_positive(self, timeout: float) -> None:
        with pytest.raises(ValueError, match="finite positive timeout"):
            Implementation(name="sorter", command=("./sorter",), timeout_seconds=timeout)

    def test_keeps_the_environment_and_timeout_it_is_given(self) -> None:
        implementation = Implementation(
            name="sorter", command=("./sorter",), environment={"A": "1"}, timeout_seconds=2.5
        )
        assert implementation.environment == {"A": "1"}
        assert implementation.timeout_seconds == 2.5


class TestFromExecutable:
    def test_resolves_the_path_and_names_after_the_file(self, tmp_path: Path) -> None:
        executable = tmp_path / "sub" / ".." / "sorter"
        implementation = Implementation.from_executable(executable)
        assert implementation.name == "sorter"
        assert implementation.command == (str((tmp_path / "sorter").resolve()),)
        assert implementation.working_directory is None

    def test_explicit_name_overrides_the_default(self, tmp_path: Path) -> None:
        implementation = Implementation.from_executable(tmp_path / "sorter", name="fast")
        assert implementation.name == "fast"


class TestFromCommandText:
    def test_splits_like_a_shell(self) -> None:
        implementation = Implementation.from_command_text("java -jar 'My Sort.jar'")
        assert implementation.command == ("java", "-jar", "My Sort.jar")

    def test_name_defaults_to_the_text_when_no_argument_is_an_existing_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        text = "node sort.js"
        assert Implementation.from_command_text(text).name == text

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("python3 sort.py", "sort"),
            ("{python} sort.py", "sort"),
            ("java -jar build/Sort.jar", "Sort"),
            ("./build/merge_sort", "merge_sort"),
            ("python3 sort.py insertion", "sort insertion"),
            ("python3 --flag sort.py --other", "sort --other"),
            ("python3 sort.py helper.py", "helper"),
        ],
    )
    def test_name_is_the_last_existing_file_without_extension_and_the_arguments_after_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str, expected: str
    ) -> None:
        (tmp_path / "build").mkdir()
        for relative in ("sort.py", "helper.py", "build/Sort.jar", "build/merge_sort"):
            (tmp_path / relative).write_text("")
        monkeypatch.chdir(tmp_path)
        text = text.replace("{python}", sys.executable)
        assert Implementation.from_command_text(text).name == expected

    def test_a_file_named_by_a_path_gives_its_file_name(self, tmp_path: Path) -> None:
        script = tmp_path / "nested" / "sort.js"
        script.parent.mkdir()
        script.write_text("")
        assert Implementation.from_command_text(f"node {script}").name == "sort"

    def test_two_commands_running_one_script_with_other_arguments_stay_apart(
        self, tmp_path: Path
    ) -> None:
        script = tmp_path / "instrumented_sort.py"
        script.write_text("")
        names = [
            Implementation.from_command_text(f"python3 {script} {algorithm}").name
            for algorithm in ("insertion", "merge")
        ]
        assert names == ["instrumented_sort insertion", "instrumented_sort merge"]

    def test_a_directory_argument_does_not_name_the_implementation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "build").mkdir()
        monkeypatch.chdir(tmp_path)
        assert Implementation.from_command_text("make build").name == "make build"

    def test_explicit_name_overrides_the_default(self) -> None:
        implementation = Implementation.from_command_text("node sort.js", name="node-sort")
        assert implementation.name == "node-sort"

    @pytest.mark.parametrize("text", ["", "   "])
    def test_empty_text_is_rejected(self, text: str) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            Implementation.from_command_text(text)

    def test_unbalanced_quote_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="Could not parse command"):
            split_command_text("node 'sort.js")


class TestReferencedFiles:
    def test_returns_existing_files_resolved_against_the_working_directory(
        self, tmp_path: Path
    ) -> None:
        script = tmp_path / "sort.py"
        script.write_text("")
        implementation = Implementation(
            name="sorter",
            command=("python3", "sort.py", "--flag", "missing.py"),
            working_directory=tmp_path,
        )
        assert implementation.referenced_files() == (script.resolve(),)

    def test_includes_absolute_paths_and_ignores_directories(self, tmp_path: Path) -> None:
        script = tmp_path / "sort.py"
        script.write_text("")
        implementation = Implementation(
            name="sorter", command=(str(script), str(tmp_path), str(script))
        )
        assert implementation.referenced_files() == (script.resolve(),)

    def test_defaults_to_the_current_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        script = tmp_path / "sort.py"
        script.write_text("")
        monkeypatch.chdir(tmp_path)
        implementation = Implementation(name="sorter", command=("python3", "sort.py"))
        assert implementation.referenced_files() == (script.resolve(),)


class TestValidateImplementations:
    def test_accepts_unique_names(self) -> None:
        validate_implementations(
            [
                Implementation(name="a", command=("a",)),
                Implementation(name="b", command=("b",)),
            ]
        )

    def test_rejects_an_empty_sequence(self) -> None:
        with pytest.raises(ValueError, match="At least one implementation"):
            validate_implementations([])

    def test_rejects_duplicate_names(self) -> None:
        with pytest.raises(ValueError, match="Duplicate implementation name: 'a'"):
            validate_implementations(
                [
                    Implementation(name="a", command=("one",)),
                    Implementation(name="a", command=("two",)),
                ]
            )
