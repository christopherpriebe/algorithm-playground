"""Tests for saving the inputs of failing cases."""

import hashlib
from pathlib import Path

import pytest
from typing_extensions import override

from algorithm_playground.core import (
    INPUT_FILE_NAME,
    SHRUNK_INPUT_FILE_NAME,
    SavedInputs,
    TestReport,
    TestRunOptions,
    make_safe_file_name,
    resolve_case,
    run_tests,
    save_failing_inputs,
)
from algorithm_playground.problems.sorting import SortingProblem
from helpers.fakes import (
    FakeRunners,
    build_named_implementations,
    crash,
    drop_last_above_five,
    sort_correctly,
)

LARGE = "generated:uniform:size=12:seed=5"


class TwelveElementUnwritableProblem(SortingProblem):
    """The sorting problem that cannot write inputs of twelve elements."""

    @override
    def serialize_input(self, data: list[int], path: Path) -> None:
        if len(data) == 12:
            message = "no room"
            raise ValueError(message)
        super().serialize_input(data, path)


def compute_digest(text: str) -> str:
    """Compute the short digest that a safe file name ends in."""
    return hashlib.sha256(text.encode()).hexdigest()[:8]


def build_test_report(
    *identifiers: str, options: TestRunOptions | None = None
) -> TestReport:
    """Run the good, bad and crashing implementations on the cases and report the results."""
    problem = SortingProblem()
    return run_tests(
        problem,
        build_named_implementations("good", "bad", "crashing"),
        [resolve_case(problem, identifier) for identifier in identifiers],
        options=options or TestRunOptions(),
        runner_factory=FakeRunners(
            {"good": sort_correctly, "bad": drop_last_above_five, "crashing": crash}
        ),
    )


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
    ids=[
        "space",
        "colons",
        "fixture",
        "separators",
        "empty",
        "dots",
        "leading-dot",
    ],
)
def test_a_name_with_replaced_characters_ends_in_a_digest_of_the_original(
    text: str, replaced: str
) -> None:
    """Test a changed name keeps its safe characters and ends in a digest of the original."""
    file_name = make_safe_file_name(text)

    assert file_name == f"{replaced}-{compute_digest(text)}"


@pytest.mark.parametrize(
    ("first", "second"),
    [("a b", "a_b"), ("a:b", "a/b")],
    ids=["space-and-underscore", "colon-and-slash"],
)
def test_two_names_that_become_the_same_text_stay_different(
    first: str, second: str
) -> None:
    """Test names that map to the same replaced text still get different file names."""
    first_file_name = make_safe_file_name(first)
    second_file_name = make_safe_file_name(second)

    assert first_file_name != second_file_name


def test_a_name_that_needs_no_change_is_returned_as_it_is() -> None:
    """Test a name made only of safe characters is not changed."""
    file_name = make_safe_file_name("plain-name_1.2+3=4")

    assert file_name == "plain-name_1.2+3=4"


def test_names_that_differ_only_in_case_stay_different_on_a_case_insensitive_file_system() -> (
    None
):
    """Test names that differ only in case differ even when compared in lower case."""
    first = make_safe_file_name("Sorter")
    second = make_safe_file_name("sorter")

    assert second == "sorter"
    assert first == f"Sorter-{compute_digest('Sorter')}"
    assert first.lower() != second.lower()


def test_a_long_name_is_cut_and_keeps_a_digest_so_that_two_long_names_differ() -> None:
    """Test a long name is cut to eighty characters and two long names still differ."""
    first = make_safe_file_name("a" * 200 + "1")
    second = make_safe_file_name("a" * 200 + "2")

    assert len(first) == len(second) == 80
    assert first != second


def test_a_short_name_gets_no_digest() -> None:
    """Test a name of exactly eighty safe characters is returned unchanged."""
    file_name = make_safe_file_name("x" * 80)

    assert file_name == "x" * 80


def test_each_failing_case_is_saved_under_its_implementation(tmp_path: Path) -> None:
    """Test an input is saved for every failing implementation and case pair, and no other."""
    report = build_test_report(LARGE, "fixture:duplicates", "fixture:empty")

    saved = save_failing_inputs(SortingProblem(), report, tmp_path / "failures")

    assert saved.errors == ()
    assert sorted(saved.inputs) == [
        ("bad", "fixture:duplicates"),
        ("bad", LARGE),
        ("crashing", "fixture:duplicates"),
        ("crashing", "fixture:empty"),
        ("crashing", LARGE),
    ]


def test_an_input_is_saved_in_a_directory_named_after_the_implementation_and_case(
    tmp_path: Path,
) -> None:
    """Test the input file lies in a directory per implementation and per safe case name."""
    report = build_test_report(LARGE)

    saved = save_failing_inputs(SortingProblem(), report, tmp_path / "failures")

    path = saved.input_path("bad", LARGE)
    assert path is not None
    assert path == (
        tmp_path
        / "failures"
        / "bad"
        / f"generated_uniform_size=12_seed=5-{compute_digest(LARGE)}"
        / "input.bin"
    )
    assert path.name == INPUT_FILE_NAME


def test_implementations_that_differ_only_in_case_or_punctuation_never_share_a_directory(
    tmp_path: Path,
) -> None:
    """Test each of four similarly named implementations saves into its own directory."""
    problem = SortingProblem()
    case = resolve_case(problem, LARGE)
    names = ("Sorter", "sorter", "sort er", "sort_er")
    report = run_tests(
        problem,
        build_named_implementations(*names),
        [case],
        options=TestRunOptions(shrinking=None),
        runner_factory=FakeRunners(dict.fromkeys(names, drop_last_above_five)),
    )

    saved = save_failing_inputs(problem, report, tmp_path)

    paths = [saved.input_path(name, LARGE) for name in names]
    assert all(path is not None for path in paths)
    directories = [path.parent.parent for path in paths if path is not None]
    assert len({str(directory).lower() for directory in directories}) == len(names)


def test_nothing_is_saved_for_a_passing_case_or_implementation(tmp_path: Path) -> None:
    """Test no input is saved for a passing implementation or a case that passed."""
    report = build_test_report("fixture:empty")

    saved = save_failing_inputs(SortingProblem(), report, tmp_path)

    assert saved.input_path("good", "fixture:empty") is None
    assert saved.input_path("bad", "fixture:empty") is None
    assert not (tmp_path / "good").exists()
    assert not (tmp_path / "bad").exists()


def test_the_file_holds_the_input_in_the_problems_format(tmp_path: Path) -> None:
    """Test the saved file deserializes to the input of the failing case."""
    problem = SortingProblem()

    saved = save_failing_inputs(problem, build_test_report(LARGE), tmp_path)

    path = saved.input_path("bad", LARGE)
    assert path is not None
    assert problem.deserialize_input(path) == resolve_case(problem, LARGE).input_data


def test_the_shrunk_input_is_saved_next_to_it(tmp_path: Path) -> None:
    """Test the shrunk input is a file beside the full input."""
    saved = save_failing_inputs(SortingProblem(), build_test_report(LARGE), tmp_path)

    shrunk_path = saved.shrunk_input_path("bad", LARGE)
    full_path = saved.input_path("bad", LARGE)
    assert shrunk_path is not None
    assert full_path is not None
    assert shrunk_path.name == SHRUNK_INPUT_FILE_NAME
    assert shrunk_path.parent == full_path.parent


def test_the_shrunk_file_holds_the_shrunk_input(tmp_path: Path) -> None:
    """Test the shrunk file deserializes to the smallest input that still fails."""
    problem = SortingProblem()

    saved = save_failing_inputs(problem, build_test_report(LARGE), tmp_path)

    shrunk_path = saved.shrunk_input_path("bad", LARGE)
    assert shrunk_path is not None
    assert problem.deserialize_input(shrunk_path) == [0] * 6


def test_a_case_that_was_not_shrunk_has_no_shrunk_file(tmp_path: Path) -> None:
    """Test an unshrunk case saves its full input and no shrunk input."""
    report = build_test_report(LARGE, options=TestRunOptions(shrinking=None))

    saved = save_failing_inputs(SortingProblem(), report, tmp_path)

    assert saved.shrunk_input_path("bad", LARGE) is None
    assert saved.input_path("bad", LARGE) is not None


def test_an_input_that_cannot_be_written_is_recorded_as_an_error(
    tmp_path: Path,
) -> None:
    """Test an input that fails to serialize is reported in the errors and not saved."""
    report = build_test_report(LARGE, "fixture:duplicates")

    saved = save_failing_inputs(TwelveElementUnwritableProblem(), report, tmp_path)

    assert saved.input_path("bad", LARGE) is None
    assert any("ValueError: no room" in error for error in saved.errors)


def test_an_input_that_cannot_be_written_does_not_stop_the_others_from_being_saved(
    tmp_path: Path,
) -> None:
    """Test the inputs that can be written are saved when another input cannot be."""
    report = build_test_report(LARGE, "fixture:duplicates")

    saved = save_failing_inputs(TwelveElementUnwritableProblem(), report, tmp_path)

    assert saved.input_path("bad", "fixture:duplicates") is not None
    assert saved.shrunk_input_path("bad", LARGE) is not None


def test_a_directory_that_cannot_be_created_is_an_error_not_an_exception(
    tmp_path: Path,
) -> None:
    """Test a failure to create the directory is recorded as an error and nothing is saved."""
    blocker = tmp_path / "blocker"
    blocker.write_text("a file")

    saved = save_failing_inputs(
        SortingProblem(), build_test_report(LARGE), blocker / "below"
    )

    assert saved.inputs == {}
    assert saved.errors
    assert "Could not save" in saved.errors[0]


def test_an_empty_result_looks_up_nothing() -> None:
    """Test an empty result has neither an input nor a shrunk input for any pair."""
    saved = SavedInputs()

    assert saved.input_path("a", "b") is None
    assert saved.shrunk_input_path("a", "b") is None
