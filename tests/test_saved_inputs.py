"""Tests for saving the inputs that made implementations fail."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fakes import FakeRunners, crash, drop_last_above_five, named, sort_correctly

from algorithm_playground.core.cases import resolve_case
from algorithm_playground.core.saved_inputs import (
    INPUT_FILE_NAME,
    SHRUNK_INPUT_FILE_NAME,
    SavedInputs,
    safe_file_name,
    save_failing_inputs,
)
from algorithm_playground.core.testing import TestReport, run_tests
from algorithm_playground.problems.sorting import SortingProblem

LARGE = "generated:uniform:size=12:seed=5"


def digest_of(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:8]


def report_of(*identifiers: str, shrink: bool = True) -> TestReport:
    problem = SortingProblem()
    return run_tests(
        problem,
        named("good", "bad", "crashing"),
        [resolve_case(problem, identifier) for identifier in identifiers],
        shrink=shrink,
        runner_factory=FakeRunners(
            {"good": sort_correctly, "bad": drop_last_above_five, "crashing": crash}
        ),
    )


class TestSafeFileName:
    @pytest.mark.parametrize(
        ("text", "replaced"),
        [
            ("python3 sort.py", "python3_sort.py"),
            ("generated:uniform:size=37:seed=5", "generated_uniform_size=37_seed=5"),
            ("fixture:empty", "fixture_empty"),
            ("a/b\\c", "a_b_c"),
            ("", "_"),
            ("..", "_."),
            (".hidden", "_hidden"),
        ],
    )
    def test_a_name_with_replaced_characters_ends_in_a_digest_of_the_original(
        self, text: str, replaced: str
    ) -> None:
        assert safe_file_name(text) == f"{replaced}-{digest_of(text)}"

    def test_two_names_that_become_the_same_text_stay_different(self) -> None:
        assert safe_file_name("a b") != safe_file_name("a_b")
        assert safe_file_name("a:b") != safe_file_name("a/b")

    def test_a_name_that_needs_no_change_is_returned_as_it_is(self) -> None:
        assert safe_file_name("plain-name_1.2+3=4") == "plain-name_1.2+3=4"

    def test_names_that_differ_only_in_case_stay_different_on_a_case_insensitive_file_system(
        self,
    ) -> None:
        first, second = safe_file_name("Sorter"), safe_file_name("sorter")
        assert second == "sorter"
        assert first == f"Sorter-{digest_of('Sorter')}"
        assert first.lower() != second.lower()

    def test_a_long_name_is_cut_and_keeps_a_digest_so_that_two_long_names_differ(self) -> None:
        first, second = safe_file_name("a" * 200 + "1"), safe_file_name("a" * 200 + "2")
        assert len(first) == len(second) == 80
        assert first != second

    def test_a_short_name_gets_no_digest(self) -> None:
        assert safe_file_name("x" * 80) == "x" * 80


class TestSaveFailingInputs:
    def test_each_failing_case_is_saved_under_its_implementation(self, tmp_path: Path) -> None:
        report = report_of(LARGE, "fixture:duplicates", "fixture:empty")
        saved = save_failing_inputs(SortingProblem(), report, tmp_path / "failures")
        assert saved.errors == ()
        assert sorted(key for key in saved.inputs) == [
            ("bad", "fixture:duplicates"),
            ("bad", LARGE),
            ("crashing", "fixture:duplicates"),
            ("crashing", "fixture:empty"),
            ("crashing", LARGE),
        ]
        path = saved.input_path("bad", LARGE)
        assert path == (
            tmp_path
            / "failures"
            / "bad"
            / f"generated_uniform_size=12_seed=5-{digest_of(LARGE)}"
            / "input.bin"
        )
        assert path is not None and path.name == INPUT_FILE_NAME

    def test_implementations_that_differ_only_in_case_or_punctuation_never_share_a_directory(
        self, tmp_path: Path
    ) -> None:
        problem = SortingProblem()
        case = resolve_case(problem, LARGE)
        names = ("Sorter", "sorter", "sort er", "sort_er")
        report = run_tests(
            problem,
            named(*names),
            [case],
            shrink=False,
            runner_factory=FakeRunners(dict.fromkeys(names, drop_last_above_five)),
        )
        saved = save_failing_inputs(problem, report, tmp_path)
        paths = [saved.input_path(name, LARGE) for name in names]
        assert all(path is not None for path in paths)
        directories = [path.parent.parent for path in paths if path is not None]
        assert len({str(directory).lower() for directory in directories}) == len(names)

    def test_nothing_is_saved_for_a_passing_case_or_implementation(self, tmp_path: Path) -> None:
        report = report_of("fixture:empty")
        saved = save_failing_inputs(SortingProblem(), report, tmp_path)
        assert saved.input_path("good", "fixture:empty") is None
        assert saved.input_path("bad", "fixture:empty") is None
        assert not (tmp_path / "good").exists()
        assert not (tmp_path / "bad").exists()

    def test_the_file_holds_the_input_in_the_problems_format(self, tmp_path: Path) -> None:
        problem = SortingProblem()
        saved = save_failing_inputs(problem, report_of(LARGE), tmp_path)
        path = saved.input_path("bad", LARGE)
        assert path is not None
        assert problem.deserialize_input(path) == resolve_case(problem, LARGE).input_data

    def test_the_shrunk_input_is_saved_next_to_it(self, tmp_path: Path) -> None:
        problem = SortingProblem()
        saved = save_failing_inputs(problem, report_of(LARGE), tmp_path)
        path = saved.shrunk_input_path("bad", LARGE)
        full = saved.input_path("bad", LARGE)
        assert path is not None and full is not None
        assert path.name == SHRUNK_INPUT_FILE_NAME and path.parent == full.parent
        assert problem.deserialize_input(path) == [0] * 6

    def test_a_case_that_was_not_shrunk_has_no_shrunk_file(self, tmp_path: Path) -> None:
        saved = save_failing_inputs(SortingProblem(), report_of(LARGE, shrink=False), tmp_path)
        assert saved.shrunk_input_path("bad", LARGE) is None
        assert saved.input_path("bad", LARGE) is not None

    def test_an_input_that_cannot_be_written_is_an_error_and_the_others_are_saved(
        self, tmp_path: Path
    ) -> None:
        class CannotWrite(SortingProblem):
            def serialize_input(self, data: list[int], path: Path) -> None:
                if len(data) == 12:
                    raise ValueError("no room")
                super().serialize_input(data, path)

        saved = save_failing_inputs(CannotWrite(), report_of(LARGE, "fixture:duplicates"), tmp_path)
        assert saved.input_path("bad", LARGE) is None
        assert saved.input_path("bad", "fixture:duplicates") is not None
        assert any("ValueError: no room" in error for error in saved.errors)
        assert saved.shrunk_input_path("bad", LARGE) is not None

    def test_a_directory_that_cannot_be_created_is_an_error_not_an_exception(
        self, tmp_path: Path
    ) -> None:
        blocker = tmp_path / "blocker"
        blocker.write_text("a file")
        saved = save_failing_inputs(SortingProblem(), report_of(LARGE), blocker / "below")
        assert saved.inputs == {}
        assert saved.errors and "Could not save" in saved.errors[0]

    def test_an_empty_result_looks_up_nothing(self) -> None:
        assert SavedInputs().input_path("a", "b") is None
        assert SavedInputs().shrunk_input_path("a", "b") is None
