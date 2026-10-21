"""How the ``test`` command shows a test report.

The matrix has one row for all the fixtures (``24/24``, expanded into one row
per fixture that did not pass, or into every fixture with ``--verbose``) and one
row per distribution, with the generated cases summarized as ``passed/total``.
Failures follow, grouped by implementation, with failures that come down to the
same shrunk input (or the same kind of failure) collapsed into one block and the
smallest failing inputs first. Everything here only prints; the report comes from
:func:`~algorithm_playground.core.testing.run_tests`.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from algorithm_playground.cli.rendering import print_table
from algorithm_playground.core.cases import Case, FixtureOrigin, GeneratedOrigin
from algorithm_playground.core.saved_inputs import SavedInputs
from algorithm_playground.core.single_run import WRONG_OUTPUT_CATEGORY
from algorithm_playground.core.testing import CaseOutcome, CaseStatus, FailureDetail, TestReport

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


def description_limit(console: Console) -> int:
    """Return how long a description of an input or output may be to fit on a line of ``console``."""
    return max(console.width - DESCRIPTION_OVERHEAD, MINIMUM_DESCRIPTION_LIMIT)


@dataclass(frozen=True)
class _MatrixRow:
    """One matrix row: a single case, or a count over several cases."""

    label: str
    identifiers: tuple[str, ...]
    counted: bool


def print_matrix(
    console: Console,
    report: TestReport,
    names: Sequence[str],
    build_failures: Collection[str],
    unrunnable: Collection[str] = (),
    *,
    verbose: bool = False,
) -> None:
    """Print the matrix of the cases against the implementations.

    ``names`` are all the selected implementations; those in ``build_failures`` or
    ``unrunnable`` did not run and show why instead of results.
    """
    table = Table()
    table.add_column("case", style="bold", overflow="fold")
    for name in names:
        table.add_column(escape(name), justify="center")
    ran = [name for name in names if name in report.implementation_names]
    fixture_rows = _fixture_rows(report, ran, verbose=verbose)
    distribution_rows = _distribution_rows(report)
    for rows in (fixture_rows, distribution_rows):
        if rows and table.row_count:
            table.add_section()
        for row in rows:
            cells = [
                BUILD_FAILED_MARKUP
                if name in build_failures
                else CANNOT_RUN_MARKUP
                if name in unrunnable
                else _matrix_cell(report, row, name)
                for name in names
            ]
            table.add_row(escape(row.label), *cells)
    print_table(console, f"test results — {report.problem_name}", table)


def _fixture_rows(report: TestReport, ran: Sequence[str], *, verbose: bool) -> list[_MatrixRow]:
    """Return the fixtures as one counted row, then a row for each that did not pass.

    With ``verbose`` every fixture has a row of its own and there is no counted row.
    """
    fixtures = [case for case in report.cases if not isinstance(case.origin, GeneratedOrigin)]
    if not fixtures:
        return []
    if verbose:
        return [_MatrixRow(_fixture_label(case), (case.identifier,), False) for case in fixtures]
    return [
        _MatrixRow(FIXTURES_LABEL, tuple(case.identifier for case in fixtures), True),
        *(
            _MatrixRow(f"{FIXTURE_INDENT}{_fixture_label(case)}", (case.identifier,), False)
            for case in fixtures
            if any(
                report.outcome(case.identifier, name).status is not CaseStatus.PASSED
                for name in ran
            )
        ),
    ]


def _distribution_rows(report: TestReport) -> list[_MatrixRow]:
    grouped: dict[str, list[str]] = {}
    for case in report.cases:
        if isinstance(case.origin, GeneratedOrigin):
            grouped.setdefault(case.origin.generator_name, []).append(case.identifier)
    return [
        _MatrixRow(generator_name, tuple(identifiers), True)
        for generator_name, identifiers in grouped.items()
    ]


def _fixture_label(case: Case[Any]) -> str:
    origin = case.origin
    return origin.name if isinstance(origin, FixtureOrigin) else case.identifier


def _matrix_cell(report: TestReport, row: _MatrixRow, implementation_name: str) -> str:
    outcomes = [report.outcome(identifier, implementation_name) for identifier in row.identifiers]
    if not row.counted:
        return STATUS_MARKUP[outcomes[0].status]
    passed = sum(outcome.status is CaseStatus.PASSED for outcome in outcomes)
    color = "green" if passed == len(outcomes) else "red"
    return f"[{color}]{passed}/{len(outcomes)}[/{color}]"


def print_failure_details(
    console: Console,
    report: TestReport,
    names: Sequence[str],
    unavailable: Collection[str],
    *,
    maximum_failures: int,
    reproduce: Callable[[str, str], str],
    saved: SavedInputs | None = None,
) -> None:
    """Describe the failures of each implementation that ran.

    Failures that come down to the same shrunk input, or to the same kind of
    failure, share a block, and the blocks are ordered by the size of the failing
    input, smallest first. ``unavailable`` names the implementations that did not
    run.
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
        groups = _group_failures(failures)
        console.print(
            f"[bold]{escape(name)}[/bold]: {len(failures)} of {len(report.cases)} cases did not pass",
            soft_wrap=True,
        )
        for group in groups[:maximum_failures]:
            _print_group(console, group, reproduce, saved)
        hidden = [outcome for group in groups[maximum_failures:] for outcome in group]
        if hidden:
            console.print(
                f"{DETAIL_INDENT}{len(hidden)} more failing cases are not described "
                f"(see --maximum-failures and --json): "
                f"{escape(_listed_identifiers(hidden))}",
                soft_wrap=True,
            )


def _group_failures(outcomes: Sequence[CaseOutcome]) -> list[list[CaseOutcome]]:
    """Group outcomes that fail alike and order the groups by their smallest input.

    Outcomes that shrank to the same input share a group, as do the others that
    have the same category of failure when the category says something (the
    problem's own, or a kind of run failure such as a timeout); the rest are
    grouped by message. Inside a group and between groups, the smaller input
    comes first.
    """
    groups: dict[tuple[object, ...], list[CaseOutcome]] = {}
    for outcome in sorted(outcomes, key=_input_weight):
        groups.setdefault(_group_key(outcome), []).append(outcome)
    return sorted(groups.values(), key=lambda group: _input_weight(group[0]))


def _group_key(outcome: CaseOutcome) -> tuple[object, ...]:
    if outcome.shrunk is not None:
        return (outcome.status, outcome.category, outcome.shrunk.detail.input_text)
    if outcome.category not in ("", WRONG_OUTPUT_CATEGORY):
        return (outcome.status, outcome.category)
    return (outcome.status, outcome.message)


def _input_weight(outcome: CaseOutcome) -> tuple[int, int]:
    """Order failures by how small the failing input is: shrunk inputs, fixtures, then by size."""
    if outcome.shrunk is not None:
        return (0, len(outcome.shrunk.detail.input_text))
    origin = outcome.case.origin
    if isinstance(origin, GeneratedOrigin):
        return (2, origin.size)
    return (1, len(outcome.detail.input_text) if outcome.detail is not None else 0)


def _print_group(
    console: Console,
    group: Sequence[CaseOutcome],
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
        console, "reproduce", reproduce(first.implementation_name, first.case_identifier)
    )
    input_path = saved.input_path(first.implementation_name, first.case_identifier)
    if input_path is not None:
        _print_labeled(console, "saved input", str(input_path))
    shrunk_path = saved.shrunk_input_path(first.implementation_name, first.case_identifier)
    if shrunk_path is not None:
        _print_labeled(console, "saved shrunk input", str(shrunk_path))
    if len(group) > 1:
        _print_labeled(console, "same failure on", _listed_identifiers(group[1:]))


def print_failure_detail(console: Console, detail: FailureDetail, *, prefix: str = "") -> None:
    """Print the input, the expected output and the actual output of a failure, one labeled line each."""
    _print_labeled(console, f"{prefix}input", detail.input_text)
    if detail.expected_text is not None:
        _print_labeled(console, f"{prefix}expected", detail.expected_text)
    if detail.actual_text is not None:
        _print_labeled(console, f"{prefix}actual", detail.actual_text)


def _print_labeled(console: Console, label: str, text: str) -> None:
    lines = text.splitlines() or [""]
    console.print(f"{DETAIL_INDENT}{label}: {escape(lines[0])}", soft_wrap=True)
    for line in lines[1:]:
        console.print(f"{DETAIL_INDENT}{DETAIL_INDENT}{escape(line)}", soft_wrap=True)


def _listed_identifiers(outcomes: Sequence[CaseOutcome]) -> str:
    identifiers = [outcome.case_identifier for outcome in outcomes]
    listed = ", ".join(identifiers[:LISTED_IDENTIFIER_LIMIT])
    if len(identifiers) > LISTED_IDENTIFIER_LIMIT:
        listed += f", and {len(identifiers) - LISTED_IDENTIFIER_LIMIT} more"
    return listed


def print_summaries(
    console: Console,
    report: TestReport,
    names: Sequence[str],
    build_failures: Collection[str],
    unrunnable: Collection[str] = (),
) -> None:
    fixture_identifiers = {
        case.identifier for case in report.cases if not isinstance(case.origin, GeneratedOrigin)
    }
    for name in names:
        if name in build_failures:
            console.print(f"[red]{escape(name)}: build failed, not run[/red]", soft_wrap=True)
            continue
        if name in unrunnable:
            console.print(f"[red]{escape(name)}: cannot run, not run[/red]", soft_wrap=True)
            continue
        outcomes = report.outcomes_for(name)
        passed = sum(outcome.status is CaseStatus.PASSED for outcome in outcomes)
        parts = []
        for noun, selected in (
            (
                "fixtures",
                [outcome for outcome in outcomes if outcome.case_identifier in fixture_identifiers],
            ),
            (
                "generated",
                [
                    outcome
                    for outcome in outcomes
                    if outcome.case_identifier not in fixture_identifiers
                ],
            ),
        ):
            if selected:
                kind_passed = sum(outcome.status is CaseStatus.PASSED for outcome in selected)
                parts.append(f"{kind_passed}/{len(selected)} {noun}")
        detail = f" ({', '.join(parts)})" if len(parts) > 1 else ""
        color = "green" if passed == len(outcomes) else "red"
        console.print(
            f"[{color}]{escape(name)}: {passed}/{len(outcomes)} cases passed{detail}[/{color}]",
            soft_wrap=True,
        )
