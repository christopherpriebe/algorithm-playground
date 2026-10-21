"""Tests for fixtures, generators, case identifiers, and case plans."""

from __future__ import annotations

import random
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from algorithm_playground.core.cases import (
    Case,
    CaseError,
    CaseOrigin,
    CasePlan,
    Fixture,
    FixtureOrigin,
    GeneratedOrigin,
    InputGenerator,
    ShrunkOrigin,
    build_cases,
    check_sizes,
    default_generator,
    generate_case,
    parse_case_identifier,
    problem_fixtures,
    problem_generators,
    resolve_case,
    select_generators,
    startup_case,
)
from algorithm_playground.core.hooks import HookError
from algorithm_playground.core.problem import Problem, VerificationResult


class TwoGeneratorProblem(Problem[list[int], list[int], None]):
    """A problem with two generators, where the second ignores the random generator."""

    name = "two-generators"
    description = "Test problem."

    def serialize_input(self, data: list[int], path: Path) -> None:
        path.write_bytes(b"")

    def deserialize_output(self, path: Path) -> list[int]:
        return []

    def fixtures(self) -> Iterator[Fixture[list[int]]]:
        yield Fixture("empty", [])
        yield Fixture("pair", [2, 1])

    def generators(self) -> Sequence[InputGenerator[list[int]]]:
        return (
            InputGenerator(
                "random",
                "random values",
                lambda random_generator, size: [
                    random_generator.randrange(100) for _ in range(size)
                ],
            ),
            InputGenerator("zeros", "all zeros", lambda random_generator, size: [0] * size),
        )

    def verify(self, input_data: list[int], output: list[int]) -> VerificationResult:
        return VerificationResult(True)


class NoGeneratorProblem(TwoGeneratorProblem):
    name = "no-generators"

    def generators(self) -> Sequence[InputGenerator[list[int]]]:
        return ()


class NeedsThreeProblem(TwoGeneratorProblem):
    """A problem whose inputs have at least three elements."""

    name = "needs-three"
    minimum_size = 3

    def fixtures(self) -> Iterator[Fixture[list[int]]]:
        yield Fixture("three", [3, 2, 1], "the smallest reversed input")


def generated_origin(case: Case[list[int]]) -> GeneratedOrigin:
    assert isinstance(case.origin, GeneratedOrigin)
    return case.origin


@pytest.fixture
def problem() -> TwoGeneratorProblem:
    return TwoGeneratorProblem()


class TestIdentifiers:
    @pytest.mark.parametrize(
        ("origin", "identifier"),
        [
            (FixtureOrigin("empty"), "fixture:empty"),
            (
                GeneratedOrigin("nearly_sorted", 1234567, 37),
                "generated:nearly_sorted:size=37:seed=1234567",
            ),
            (ShrunkOrigin("fixture:empty"), "shrunk:fixture:empty"),
        ],
    )
    def test_origins_print_stable_identifiers(self, origin: CaseOrigin, identifier: str) -> None:
        assert Case(origin, []).identifier == identifier

    @pytest.mark.parametrize(
        "origin",
        [
            FixtureOrigin("empty"),
            FixtureOrigin("name:with:colons"),
            GeneratedOrigin("nearly_sorted", 1234567, 37),
            GeneratedOrigin("uniform", 0, 0),
            GeneratedOrigin("uniform", -5, 3),
        ],
    )
    def test_fixture_and_generated_identifiers_parse_back(
        self, origin: FixtureOrigin | GeneratedOrigin
    ) -> None:
        assert parse_case_identifier(Case(origin, []).identifier) == origin

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("nonsense", "Unrecognized case identifier"),
            ("fixture:", "names no fixture"),
            ("generated:uniform", "Unrecognized case identifier"),
            ("generated:uniform:size=x:seed=1", "no valid 'size=N' part"),
            ("generated:uniform:size=3:seed=", "no valid 'seed=N' part"),
            ("generated:uniform:seed=1:size=3", "no valid 'size=N' part"),
            ("generated:uniform:size=-1:seed=1", "negative size"),
            ("generated:uniform:size=05:seed=1", "no valid 'size=N' part"),
            ("generated:uniform:size=+5:seed=1", "no valid 'size=N' part"),
            ("generated:uniform:size=1_0:seed=1", "no valid 'size=N' part"),
            ("generated:uniform:size= 5:seed=1", "no valid 'size=N' part"),
            ("generated:uniform:size=5:seed=007", "no valid 'seed=N' part"),
            ("generated:uniform:size=5:seed=+7", "no valid 'seed=N' part"),
            ("generated:uniform:size=5:seed=-0", "no valid 'seed=N' part"),
            ("generated:uniform:size=5:seed=1 ", "no valid 'seed=N' part"),
            ("generated::size=1:seed=1", "Unrecognized case identifier"),
            ("shrunk:fixture:empty", "cannot be replayed"),
        ],
    )
    def test_malformed_identifiers_are_rejected(self, text: str, message: str) -> None:
        with pytest.raises(CaseError, match=message):
            parse_case_identifier(text)


class TestResolveCase:
    def test_a_fixture_is_found_by_name(self, problem: TwoGeneratorProblem) -> None:
        case = resolve_case(problem, "fixture:pair")
        assert case.input_data == [2, 1]
        assert case.origin == FixtureOrigin("pair")

    def test_a_fixture_case_carries_the_description_of_the_fixture(self) -> None:
        origin = resolve_case(NeedsThreeProblem(), "fixture:three").origin
        assert isinstance(origin, FixtureOrigin)
        assert origin.description == "the smallest reversed input"
        assert origin == FixtureOrigin("three")

    def test_a_size_below_the_minimum_of_the_problem_is_an_error(self) -> None:
        with pytest.raises(CaseError, match="at least 3 elements"):
            resolve_case(NeedsThreeProblem(), "generated:random:size=2:seed=1")

    def test_an_unknown_fixture_lists_the_available_ones(
        self, problem: TwoGeneratorProblem
    ) -> None:
        with pytest.raises(
            CaseError, match=r"No fixture named 'nope'. Available fixtures: empty, pair"
        ):
            resolve_case(problem, "fixture:nope")

    def test_a_generated_case_is_rebuilt_exactly(self, problem: TwoGeneratorProblem) -> None:
        original = generate_case(problem.generators()[0], size=12, seed=99)
        assert resolve_case(problem, original.identifier) == original

    def test_an_unknown_generator_lists_the_available_ones(
        self, problem: TwoGeneratorProblem
    ) -> None:
        with pytest.raises(
            CaseError,
            match=r"Unknown distribution 'nope'\. Available distributions: random, zeros",
        ):
            resolve_case(problem, "generated:nope:size=1:seed=1")


class TestGenerateCase:
    def test_uses_a_random_generator_seeded_with_the_seed(
        self, problem: TwoGeneratorProblem
    ) -> None:
        case = generate_case(problem.generators()[0], size=5, seed=7)
        expected = random.Random(7)
        assert case.input_data == [expected.randrange(100) for _ in range(5)]
        assert case.origin == GeneratedOrigin("random", 7, 5)

    def test_rejects_a_negative_size(self, problem: TwoGeneratorProblem) -> None:
        with pytest.raises(CaseError, match="negative"):
            generate_case(problem.generators()[0], size=-1, seed=0)

    def test_the_default_generator_is_the_first(self, problem: TwoGeneratorProblem) -> None:
        assert default_generator(problem).name == "random"

    def test_a_problem_without_generators_has_no_default(self) -> None:
        with pytest.raises(CaseError, match="defines no input distributions"):
            default_generator(NoGeneratorProblem())

    def test_startup_case_is_the_default_generator_at_the_minimum_size(
        self, problem: TwoGeneratorProblem
    ) -> None:
        case = startup_case(problem, seed=5)
        assert case.input_data == []
        assert case.identifier == "generated:random:size=0:seed=5"

    def test_startup_case_follows_the_minimum_size_of_the_problem(self) -> None:
        case = startup_case(NeedsThreeProblem(), seed=5)
        assert len(case.input_data) == 3
        assert case.identifier == "generated:random:size=3:seed=5"

    def test_check_sizes_names_the_sizes_that_are_too_small(self) -> None:
        check_sizes(NeedsThreeProblem(), (3, 4))
        with pytest.raises(CaseError, match=r"at least 3 elements, but the sizes include 0, 2"):
            check_sizes(NeedsThreeProblem(), (2, 5, 0))


class TestCasePlan:
    def test_rejects_a_negative_random_case_count(self) -> None:
        with pytest.raises(CaseError, match="case count"):
            CasePlan(random_case_count=-1)

    def test_rejects_a_negative_maximum_size(self) -> None:
        with pytest.raises(CaseError, match="maximum size"):
            CasePlan(maximum_size=-1)


class TestBuildCases:
    def test_fixtures_come_first_then_generated_cases(self, problem: TwoGeneratorProblem) -> None:
        cases = build_cases(problem, CasePlan(random_case_count=4))
        assert [case.identifier for case in cases[:2]] == ["fixture:empty", "fixture:pair"]
        assert all(isinstance(case.origin, GeneratedOrigin) for case in cases[2:])
        assert len(cases) == 6

    def test_the_plan_is_deterministic_and_the_seed_changes_it(
        self, problem: TwoGeneratorProblem
    ) -> None:
        plan = CasePlan(random_case_count=10, seed=3)
        assert build_cases(problem, plan) == build_cases(problem, plan)
        other = build_cases(problem, CasePlan(random_case_count=10, seed=4))
        assert build_cases(problem, plan) != other

    def test_generators_take_turns_and_shift_by_one_every_round(
        self, problem: TwoGeneratorProblem
    ) -> None:
        cases = build_cases(problem, CasePlan(include_fixtures=False, random_case_count=6))
        names = [generated_origin(case).generator_name for case in cases]
        assert names == ["random", "zeros", "zeros", "random", "random", "zeros"]

    @pytest.mark.parametrize("generator_count", [2, 3, 4])
    def test_every_generator_covers_the_whole_range_of_sizes(self, generator_count: int) -> None:
        class ManyGeneratorProblem(TwoGeneratorProblem):
            def generators(self) -> Sequence[InputGenerator[list[int]]]:
                return tuple(
                    InputGenerator(f"g{number}", "zeros", lambda random_generator, size: [0] * size)
                    for number in range(generator_count)
                )

        plan = CasePlan(include_fixtures=False, random_case_count=20, maximum_size=100)
        sizes_by_generator: dict[str, list[int]] = {}
        for case in build_cases(ManyGeneratorProblem(), plan):
            origin = generated_origin(case)
            sizes_by_generator.setdefault(origin.generator_name, []).append(origin.size)
        assert len(sizes_by_generator) == generator_count
        for sizes in sizes_by_generator.values():
            assert min(sizes) <= 5
            assert max(sizes) >= 50
        largest = [max(sizes) for sizes in sizes_by_generator.values()]
        assert max(largest) - min(largest) <= 30

    def test_named_generators_restrict_the_plan(self, problem: TwoGeneratorProblem) -> None:
        plan = CasePlan(include_fixtures=False, random_case_count=3, generator_names=("zeros",))
        names = {generated_origin(case).generator_name for case in build_cases(problem, plan)}
        assert names == {"zeros"}

    def test_an_unknown_generator_name_is_an_error(self, problem: TwoGeneratorProblem) -> None:
        with pytest.raises(CaseError, match="Unknown distribution 'nope'"):
            build_cases(problem, CasePlan(generator_names=("nope",)))

    def test_no_fixtures_and_no_random_cases_gives_nothing(
        self, problem: TwoGeneratorProblem
    ) -> None:
        assert build_cases(problem, CasePlan(include_fixtures=False, random_case_count=0)) == ()

    def test_zero_random_cases_needs_no_generators(self) -> None:
        cases = build_cases(NoGeneratorProblem(), CasePlan(random_case_count=0))
        assert len(cases) == 2

    def test_random_cases_without_generators_are_an_error(self) -> None:
        with pytest.raises(CaseError, match="defines no input distributions"):
            build_cases(NoGeneratorProblem(), CasePlan())

    def test_sizes_stay_within_bounds_and_favor_small_inputs(
        self, problem: TwoGeneratorProblem
    ) -> None:
        plan = CasePlan(include_fixtures=False, random_case_count=40, maximum_size=100, seed=1)
        sizes = [generated_origin(case).size for case in build_cases(problem, plan)]
        assert min(sizes) == 0
        assert max(sizes) <= 100
        assert max(sizes) >= 70
        assert sum(size <= 30 for size in sizes) > len(sizes) / 2

    def test_sizes_start_at_the_minimum_size_of_the_problem(self) -> None:
        plan = CasePlan(include_fixtures=False, random_case_count=30, maximum_size=20)
        sizes = [generated_origin(case).size for case in build_cases(NeedsThreeProblem(), plan)]
        assert min(sizes) == 3
        assert max(sizes) <= 20

    def test_a_maximum_size_below_the_minimum_size_is_an_error(self) -> None:
        with pytest.raises(CaseError, match="maximum size 2 is below the smallest size"):
            build_cases(NeedsThreeProblem(), CasePlan(random_case_count=1, maximum_size=2))

    def test_fixtures_carry_their_descriptions(self) -> None:
        (case,) = build_cases(NeedsThreeProblem(), CasePlan(random_case_count=0))
        assert isinstance(case.origin, FixtureOrigin)
        assert case.origin.description == "the smallest reversed input"

    def test_a_maximum_size_of_zero_gives_only_empty_inputs(
        self, problem: TwoGeneratorProblem
    ) -> None:
        plan = CasePlan(include_fixtures=False, random_case_count=5, maximum_size=0)
        assert {len(case.input_data) for case in build_cases(problem, plan)} == {0}

    def test_every_generated_case_can_be_rebuilt_from_its_identifier(
        self, problem: TwoGeneratorProblem
    ) -> None:
        for case in build_cases(problem, CasePlan(random_case_count=8, seed=2)):
            assert resolve_case(problem, case.identifier) == case


class ExplodingFixturesProblem(TwoGeneratorProblem):
    name = "exploding-fixtures"

    def fixtures(self) -> Iterator[Fixture[list[int]]]:
        yield Fixture("first", [1])
        raise RuntimeError("fixtures exploded")


class ExplodingGeneratorsProblem(TwoGeneratorProblem):
    name = "exploding-generators"

    def generators(self) -> Sequence[InputGenerator[list[int]]]:
        raise RuntimeError("generators exploded")


class ExplodingGeneratorProblem(TwoGeneratorProblem):
    """The default generator works; the second one raises for every size."""

    name = "exploding-generator"

    def generators(self) -> Sequence[InputGenerator[list[int]]]:
        def explode(random_generator: random.Random, size: int) -> list[int]:
            raise RuntimeError("generator exploded")

        return (
            InputGenerator("fine", "works", lambda random_generator, size: [0] * size),
            InputGenerator("broken", "raises", explode),
        )


class WrongKindsProblem(TwoGeneratorProblem):
    name = "wrong-kinds"

    def fixtures(self) -> Iterator[Fixture[list[int]]]:
        yield ("empty", [])  # ty: ignore[invalid-yield]

    def generators(self) -> Sequence[InputGenerator[list[int]]]:
        return ("random",)  # ty: ignore[invalid-return-type]


class TestHooksThatRaise:
    def test_fixtures_that_raise_are_a_hook_error_naming_the_hook(self) -> None:
        with pytest.raises(HookError, match="The problem's fixtures hook raised RuntimeError"):
            build_cases(ExplodingFixturesProblem(), CasePlan(random_case_count=0))
        with pytest.raises(HookError, match="fixtures hook"):
            resolve_case(ExplodingFixturesProblem(), "fixture:first")
        with pytest.raises(HookError, match="fixtures hook"):
            problem_fixtures(ExplodingFixturesProblem())

    def test_a_generators_hook_that_raises_is_a_hook_error_everywhere_it_is_used(self) -> None:
        problem = ExplodingGeneratorsProblem()
        for call in (
            lambda: select_generators(problem, ()),
            lambda: problem_generators(problem),
            lambda: default_generator(problem),
            lambda: startup_case(problem, 0),
            lambda: build_cases(problem, CasePlan(include_fixtures=False)),
            lambda: resolve_case(problem, "generated:random:size=3:seed=1"),
        ):
            with pytest.raises(HookError, match="The problem's generators hook raised"):
                call()

    def test_the_function_of_a_generator_that_raises_names_the_generator(self) -> None:
        problem = ExplodingGeneratorProblem()
        for call in (
            lambda: resolve_case(problem, "generated:broken:size=3:seed=1"),
            lambda: build_cases(problem, CasePlan(include_fixtures=False)),
        ):
            with pytest.raises(HookError) as raised:
                call()
            assert str(raised.value) == (
                "The problem's 'broken' generator hook raised RuntimeError: generator exploded."
            )
        assert resolve_case(problem, "generated:fine:size=3:seed=1").input_data == [0, 0, 0]

    def test_something_that_is_not_a_fixture_or_a_generator_is_a_hook_error_too(self) -> None:
        problem = WrongKindsProblem()
        with pytest.raises(HookError, match=r"fixtures hook raised TypeError.*tuple.*Fixture"):
            problem_fixtures(problem)
        with pytest.raises(
            HookError, match=r"generators hook raised TypeError.*str.*InputGenerator"
        ):
            problem_generators(problem)

    def test_an_error_of_the_caller_is_still_a_case_error(self) -> None:
        with pytest.raises(CaseError):
            select_generators(TwoGeneratorProblem(), ("nope",))
