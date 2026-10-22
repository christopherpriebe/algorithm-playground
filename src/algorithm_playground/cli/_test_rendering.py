"""How the ``test`` command shows a test report.

The matrix has one row for all the fixtures (``24/24``, expanded into one row
per fixture that did not pass, or into every fixture with ``--verbose``) and one
row per distribution, with the generated cases summarized as ``passed/total``.
Failures follow, grouped by implementation, with failures that come down to the
same shrunk input (or the same kind of failure) collapsed into one block and the
smallest failing inputs first. Everything here only prints; the report comes from
:func:`~algorithm_playground.core.run_tests`.
"""

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from algorithm_playground.cli._rendering import print_table
from algorithm_playground.core._cases import AnyCase, FixtureOrigin, GeneratedOrigin
from algorithm_playground.core._saved_inputs import SavedInputs
from algorithm_playground.core._single_run import WRONG_OUTPUT_CATEGORY
from algorithm_playground.core._testing import (
    CaseOutcome,
    CaseStatus,
    FailureDetail,
    TestReport,
)

__all__ = [
    "description_limit",
    "print_expanded_matrix",
    "print_failure_detail",
    "print_failure_details",
    "print_matrix",
    "print_summaries",
]

LISTED_IDENTIFIER_LIMIT = 5
MINIMUM_DESCRIPTION_LIMIT = 40
# The room a description needs beside its text: the indent and the longest label.
DESCRIPTION_OVERHEAD = 24
STATUS_MARKUP = {
    CaseStatus.PASSED: "[green]PASS[/green]",
    CaseStatus.FAILED: "[red]FAIL[/red]",
    CaseStatus.ERROR: "[red]ERROR[/red]",
}
BUILD_FAILED_MARKUP = "[red]build failed[/red]"
CANNOT_RUN_MARKUP = "[red]cannot run[/red]"
FIXTURES_LABEL = "fixtures"
FIXTURE_INDENT = "  "
DETAIL_INDENT = "    "


def _fixture_cases(report: TestReport) -> list[AnyCase]:
    return [
        case for case in report.cases if not isinstance(case.origin, GeneratedOrigin)
    ]


def _fixture_label(case: AnyCase) -> str:
    origin = case.origin
    return origin.name if isinstance(origin, FixtureOrigin) else case.identifier


def _unavailable_markup(
    build_failures: Collection[str], unrunnable: Collection[str]
) -> dict[str, str]:
    """Map each implementation that did not run to the cell that says why.

    Returns:
        The cell markup by implementation name.
    """
    markup = dict.fromkeys(unrunnable, CANNOT_RUN_MARKUP)
    markup.update(dict.fromkeys(build_failures, BUILD_FAILED_MARKUP))
    return markup


def _input_weight(outcome: CaseOutcome) -> tuple[int, int]:
    """Order failures by how small the failing input is: shrunk inputs, fixtures, then by size.

    Returns:
        A pair that orders failures, smaller inputs first.
    """
    if outcome.shrunk is not None:
        return (0, len(outcome.shrunk.detail.input_text))
    origin = outcome.case.origin
    if isinstance(origin, GeneratedOrigin):
        return (2, sum(origin.size.values()))
    return (1, len(outcome.detail.input_text) if outcome.detail is not None else 0)


def _group_key(outcome: CaseOutcome) -> tuple[object, ...]:
    if outcome.shrunk is not None:
        return (outcome.status, outcome.category, outcome.shrunk.detail.input_text)
    if outcome.category not in ("", WRONG_OUTPUT_CATEGORY):
        return (outcome.status, outcome.category)
    return (outcome.status, outcome.message)


def _group_failures(outcomes: Sequence[CaseOutcome]) -> list[list[CaseOutcome]]:
    """Group outcomes that fail alike and order the groups by their smallest input.

    Outcomes that shrank to the same input share a group, as do the others that
    have the same category of failure when the category says something (the
    problem's own, or a kind of run failure such as a timeout); the rest are
    grouped by message. Inside a group and between groups, the smaller input
    comes first.

    Returns:
        The groups, each ordered by its smallest input.
    """
    groups: dict[tuple[object, ...], list[CaseOutcome]] = {}
    for outcome in sorted(outcomes, key=_input_weight):
        groups.setdefault(_group_key(outcome), []).append(outcome)
    return sorted(groups.values(), key=lambda group: _input_weight(group[0]))


def _listed_identifiers(outcomes: Sequence[CaseOutcome]) -> str:
    identifiers = [outcome.case_identifier for outcome in outcomes]
    listed = ", ".join(identifiers[:LISTED_IDENTIFIER_LIMIT])
    if len(identifiers) > LISTED_IDENTIFIER_LIMIT:
        listed += f", and {len(identifiers) - LISTED_IDENTIFIER_LIMIT} more"
    return listed


def _print_labeled(console: Console, label: str, text: str) -> None:
    lines = text.splitlines() or [""]
    console.print(f"{DETAIL_INDENT}{label}: {escape(lines[0])}", soft_wrap=True)
    for line in lines[1:]:
        console.print(f"{DETAIL_INDENT}{DETAIL_INDENT}{escape(line)}", soft_wrap=True)


def _print_saved_paths(
    console: Console, saved: SavedInputs, outcome: CaseOutcome
) -> None:
    input_path = saved.input_path(outcome.implementation_name, outcome.case_identifier)
    if input_path is not None:
        _print_labeled(console, "saved input", str(input_path))
    shrunk_path = saved.shrunk_input_path(
        outcome.implementation_name, outcome.case_identifier
    )
    if shrunk_path is not None:
        _print_labeled(console, "saved shrunk input", str(shrunk_path))


def _print_group(
    console: Console,
    group: Sequence[CaseOutcome],
    *,
    reproduce: Callable[[str, str], str],
    saved: SavedInputs,
) -> None:
    first = group[0]
    console.print(
        f"{STATUS_MARKUP[first.status]} {escape(first.implementation_name)} on "
        f"{escape(first.case_identifier)}",
        soft_wrap=True,
    )
    _print_labeled(console, "message", first.message)
    origin = first.case.origin
    if isinstance(origin, FixtureOrigin) and origin.description:
        _print_labeled(console, "fixture", origin.description)
    if first.detail is not None:
        print_failure_detail(console, first.detail)
    if first.shrunk is not None:
        print_failure_detail(console, first.shrunk.detail, prefix="shrunk ")
        _print_labeled(console, "shrunk message", first.shrunk.message)
    if first.shrink_note is not None:
        _print_labeled(console, "shrink note", first.shrink_note)
    _print_labeled(
        console,
        "reproduce",
        reproduce(first.implementation_name, first.case_identifier),
    )
    _print_saved_paths(console, saved, first)
    if len(group) > 1:
        _print_labeled(console, "same failure on", _listed_identifiers(group[1:]))


def _print_implementation_failures(  # noqa: PLR0913  the failures, limit, reproduction and saved inputs are all needed
    console: Console,
    report: TestReport,
    name: str,
    *,
    failures: Sequence[CaseOutcome],
    maximum_failures: int,
    reproduce: Callable[[str, str], str],
    saved: SavedInputs,
) -> None:
    groups = _group_failures(failures)
    console.print(
        f"[bold]{escape(name)}[/bold]: {len(failures)} of {len(report.cases)} cases did not pass",
        soft_wrap=True,
    )
    for group in groups[:maximum_failures]:
        _print_group(console, group, reproduce=reproduce, saved=saved)
    hidden = [outcome for group in groups[maximum_failures:] for outcome in group]
    if hidden:
        console.print(
            f"{DETAIL_INDENT}{len(hidden)} more failing cases are not described "
            f"(see --maximum-failures and --json): "
            f"{escape(_listed_identifiers(hidden))}",
            soft_wrap=True,
        )


def _describe_passes(
    outcomes: Sequence[CaseOutcome], fixture_identifiers: Collection[str]
) -> str:
    """Describe how many fixtures and how many generated cases passed, when both ran.

    Returns:
        The description of the passes.
    """
    fixture_outcomes = [
        outcome
        for outcome in outcomes
        if outcome.case_identifier in fixture_identifiers
    ]
    generated_outcomes = [
        outcome
        for outcome in outcomes
        if outcome.case_identifier not in fixture_identifiers
    ]
    parts = []
    for noun, selected in (
        ("fixtures", fixture_outcomes),
        ("generated", generated_outcomes),
    ):
        if selected:
            passed = sum(outcome.status is CaseStatus.PASSED for outcome in selected)
            parts.append(f"{passed}/{len(selected)} {noun}")
    return f" ({', '.join(parts)})" if len(parts) > 1 else ""


def _expanded_fixture_rows(report: TestReport) -> "list[_MatrixRow]":
    """Return a row of its own for every fixture."""
    return [
        _MatrixRow(_fixture_label(case), (case.identifier,), False)
        for case in _fixture_cases(report)
    ]


def _collapsed_fixture_rows(
    report: TestReport, ran: Sequence[str]
) -> "list[_MatrixRow]":
    """Return the fixtures as one counted row, then a row for each that did not pass."""
    fixtures = _fixture_cases(report)
    if not fixtures:
        return []
    return [
        _MatrixRow(FIXTURES_LABEL, tuple(case.identifier for case in fixtures), True),
        *(
            _MatrixRow(
                f"{FIXTURE_INDENT}{_fixture_label(case)}", (case.identifier,), False
            )
            for case in fixtures
            if any(
                report.outcome(case.identifier, name).status is not CaseStatus.PASSED
                for name in ran
            )
        ),
    ]


def _distribution_rows(report: TestReport) -> "list[_MatrixRow]":
    grouped: dict[str, list[str]] = {}
    for case in report.cases:
        if isinstance(case.origin, GeneratedOrigin):
            grouped.setdefault(case.origin.generator_name, []).append(case.identifier)
    return [
        _MatrixRow(generator_name, tuple(identifiers), True)
        for generator_name, identifiers in grouped.items()
    ]


def _outcome_cell(
    report: TestReport, row: "_MatrixRow", implementation_name: str
) -> str:
    outcomes = [
        report.outcome(identifier, implementation_name)
        for identifier in row.identifiers
    ]
    if not row.counted:
        return STATUS_MARKUP[outcomes[0].status]
    passed = sum(outcome.status is CaseStatus.PASSED for outcome in outcomes)
    color = "green" if passed == len(outcomes) else "red"
    return f"[{color}]{passed}/{len(outcomes)}[/{color}]"


def _build_matrix_table(
    report: TestReport,
    names: Sequence[str],
    unavailable_markup: Mapping[str, str],
    *,
    fixture_rows: "Sequence[_MatrixRow]",
) -> Table:
    table = Table()
    table.add_column("case", style="bold", overflow="fold")
    for name in names:
        table.add_column(escape(name), justify="center")
    for rows in (fixture_rows, _distribution_rows(report)):
        if rows and table.row_count:
            table.add_section()
        for row in rows:
            cells = [
                unavailable_markup[name]
                if name in unavailable_markup
                else _outcome_cell(report, row, name)
                for name in names
            ]
            table.add_row(escape(row.label), *cells)
    return table


@dataclass(frozen=True, slots=True)
class _MatrixRow:
    """One matrix row: a single case, or a count over several cases."""

    label: str
    identifiers: tuple[str, ...]
    counted: bool


def description_limit(console: Console) -> int:
    """Return how long a description of an input or output may be to fit on a line.

    Args:
        console: The console the description is printed on.

    Returns:
        The number of characters a description may have.
    """
    return max(console.width - DESCRIPTION_OVERHEAD, MINIMUM_DESCRIPTION_LIMIT)


def print_matrix(
    console: Console,
    report: TestReport,
    names: Sequence[str],
    *,
    build_failures: Collection[str],
    unrunnable: Collection[str] = (),
) -> None:
    """Print the matrix of the cases against the implementations.

    The fixtures are one counted row, followed by a row for each fixture that
    did not pass. Implementations that did not run show why instead of results.

    Args:
        console: The console to print on.
        report: The test report.
        names: All the selected implementations.
        build_failures: The names of the implementations that failed to build.
        unrunnable: The names of the implementations whose command cannot start.
    """
    ran = [name for name in names if name in report.implementation_names]
    table = _build_matrix_table(
        report,
        names,
        _unavailable_markup(build_failures, unrunnable),
        fixture_rows=_collapsed_fixture_rows(report, ran),
    )
    print_table(console, f"test results — {report.problem_name}", table)


def print_expanded_matrix(
    console: Console,
    report: TestReport,
    names: Sequence[str],
    *,
    build_failures: Collection[str],
    unrunnable: Collection[str] = (),
) -> None:
    """Print the matrix of the cases against the implementations, with a row for every fixture.

    Args:
        console: The console to print on.
        report: The test report.
        names: All the selected implementations.
        build_failures: The names of the implementations that failed to build.
        unrunnable: The names of the implementations whose command cannot start.
    """
    table = _build_matrix_table(
        report,
        names,
        _unavailable_markup(build_failures, unrunnable),
        fixture_rows=_expanded_fixture_rows(report),
    )
    print_table(console, f"test results — {report.problem_name}", table)


def print_failure_details(  # noqa: PLR0913  the report, selection, limit, reproduction and saved inputs are all needed
    console: Console,
    report: TestReport,
    names: Sequence[str],
    *,
    unavailable: Collection[str],
    maximum_failures: int,
    reproduce: Callable[[str, str], str],
    saved: SavedInputs | None = None,
) -> None:
    """Describe the failures of each implementation that ran.

    Failures that come down to the same shrunk input, or to the same kind of
    failure, share a block, and the blocks are ordered by the size of the failing
    input, smallest first.

    Args:
        console: The console to print on.
        report: The test report.
        names: All the selected implementations.
        unavailable: The names of the implementations that did not run.
        maximum_failures: How many blocks to describe in full per implementation.
        reproduce: Returns the command that reruns a case, given the name of the
            implementation and the identifier of the case.
        saved: The inputs written to disk, if any.
    """
    saved = saved or SavedInputs()
    for name in names:
        failures = [
            outcome
            for outcome in report.outcomes_for(name)
            if outcome.status is not CaseStatus.PASSED
        ]
        if name in unavailable or not failures:
            continue
        _print_implementation_failures(
            console,
            report,
            name,
            failures=failures,
            maximum_failures=maximum_failures,
            reproduce=reproduce,
            saved=saved,
        )


def print_failure_detail(
    console: Console, detail: FailureDetail, *, prefix: str = ""
) -> None:
    """Print the input, the expected output and the actual output of a failure.

    Args:
        console: The console to print on.
        detail: The description of the failure.
        prefix: Text put before each label.
    """
    _print_labeled(console, f"{prefix}input", detail.input_text)
    if detail.expected_text is not None:
        _print_labeled(console, f"{prefix}expected", detail.expected_text)
    if detail.actual_text is not None:
        _print_labeled(console, f"{prefix}actual", detail.actual_text)


def print_summaries(
    console: Console,
    report: TestReport,
    names: Sequence[str],
    *,
    build_failures: Collection[str],
    unrunnable: Collection[str] = (),
) -> None:
    """Print one line per implementation: how many cases passed, or why it did not run.

    Args:
        console: The console to print on.
        report: The test report.
        names: All the selected implementations.
        build_failures: The names of the implementations that failed to build.
        unrunnable: The names of the implementations whose command cannot start.
    """
    fixture_identifiers = {case.identifier for case in _fixture_cases(report)}
    for name in names:
        if name in build_failures:
            console.print(
                f"[red]{escape(name)}: build failed, not run[/red]", soft_wrap=True
            )
        elif name in unrunnable:
            console.print(
                f"[red]{escape(name)}: cannot run, not run[/red]", soft_wrap=True
            )
        else:
            outcomes = report.outcomes_for(name)
            passed = sum(outcome.status is CaseStatus.PASSED for outcome in outcomes)
            detail = _describe_passes(outcomes, fixture_identifiers)
            color = "green" if passed == len(outcomes) else "red"
            console.print(
                f"[{color}]{escape(name)}: {passed}/{len(outcomes)} cases passed{detail}[/{color}]",
                soft_wrap=True,
            )
