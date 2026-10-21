"""Tests for fixtures, generators, case identifiers, and case plans."""

import random
from collections.abc import Callable, Iterator, Sequence
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


def generate_random_values(random_generator: random.Random, size: int) -> list[int]:
    """Generate ``size`` random values below one hundred."""
    return [random_generator.randrange(100) for _ in range(size)]


def generate_zeros(random_generator: random.Random, size: int) -> list[int]:
    """Generate ``size`` zeros without using the random generator."""
    return [0] * size


def generate_by_raising(random_generator: random.Random, size: int) -> list[int]:
    """Fail for every size, as a generator that is broken."""
    raise RuntimeError("generator exploded")


def get_generated_origin(case: Case[list[int]]) -> GeneratedOrigin:
    """Return the generated origin of a case, failing the test when it has another origin."""
    assert isinstance(case.origin, GeneratedOrigin)
    return case.origin


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
            InputGenerator("random", "random values", generate_random_values),
            InputGenerator("zeros", "all zeros", generate_zeros),
        )

    def verify(self, input_data: list[int], output: list[int]) -> VerificationResult:
        return VerificationResult(True)


class NoGeneratorProblem(TwoGeneratorProblem):
    """A problem that defines no input distributions."""

    name = "no-generators"

    def generators(self) -> Sequence[InputGenerator[list[int]]]:
        return ()


class NeedsThreeProblem(TwoGeneratorProblem):
    """A problem whose inputs have at least three elements."""

    name = "needs-three"
    minimum_size = 3

    def fixtures(self) -> Iterator[Fixture[list[int]]]:
        yield Fixture("three", [3, 2, 1], "the smallest reversed input")


class ExplodingFixturesProblem(TwoGeneratorProblem):
    """A problem whose fixtures hook raises after yielding its first fixture."""

    name = "exploding-fixtures"

    def fixtures(self) -> Iterator[Fixture[list[int]]]:
        yield Fixture("first", [1])
        raise RuntimeError("fixtures exploded")


class ExplodingGeneratorsProblem(TwoGeneratorProblem):
    """A problem whose generators hook raises."""

    name = "exploding-generators"

    def generators(self) -> Sequence[InputGenerator[list[int]]]:
        raise RuntimeError("generators exploded")


class ExplodingGeneratorProblem(TwoGeneratorProblem):
    """A problem whose first generator works and whose second one raises for every size."""

    name = "exploding-generator"

    def generators(self) -> Sequence[InputGenerator[list[int]]]:
        return (
            InputGenerator("fine", "works", generate_zeros),
            InputGenerator("broken", "raises", generate_by_raising),
        )


class WrongKindsProblem(TwoGeneratorProblem):
    """A problem whose hooks return a tuple instead of a fixture and a string instead of a generator."""

    name = "wrong-kinds"

    def fixtures(self) -> Iterator[Fixture[list[int]]]:
        yield ("empty", [])  # ty: ignore[invalid-yield]

    def generators(self) -> Sequence[InputGenerator[list[int]]]:
        return ("random",)  # ty: ignore[invalid-return-type]


def build_many_generator_problem(generator_count: int) -> TwoGeneratorProblem:
    """Build a problem with ``generator_count`` generators that all produce zeros."""

    class ManyGeneratorProblem(TwoGeneratorProblem):
        def generators(self) -> Sequence[InputGenerator[list[int]]]:
            return tuple(
                InputGenerator(f"g{number}", "zeros", generate_zeros)
                for number in range(generator_count)
            )

    return ManyGeneratorProblem()


@pytest.fixture
def problem() -> TwoGeneratorProblem:
    """A problem with two generators and two fixtures."""
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
        ids=["fixture", "generated", "shrunk"],
    )
    def test_origins_print_stable_identifiers(self, origin: CaseOrigin, identifier: str) -> None:
        """Test each kind of origin gives its case a fixed identifier."""
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
        ids=[
            "fixture",
            "fixture-name-with-colons",
            "generated",
            "generated-zero-size-and-seed",
            "generated-negative-seed",
        ],
    )
    def test_fixture_and_generated_identifiers_parse_back(
        self, origin: FixtureOrigin | GeneratedOrigin
    ) -> None:
        """Test the identifier of a fixture or generated case parses back to its origin."""
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
        ids=[
            "not-an-identifier",
            "fixture-without-name",
            "generated-without-size-and-seed",
            "size-not-a-number",
            "seed-empty",
            "seed-before-size",
            "size-negative",
            "size-leading-zero",
            "size-plus-sign",
            "size-underscore",
            "size-leading-space",
            "seed-leading-zeros",
            "seed-plus-sign",
            "seed-negative-zero",
            "seed-trailing-space",
            "generator-without-name",
            "shrunk",
        ],
    )
    def test_malformed_identifiers_are_rejected(self, text: str, message: str) -> None:
        """Test an identifier that is not in the canonical form is rejected with the reason."""
        with pytest.raises(CaseError, match=message):
            parse_case_identifier(text)


class TestResolveCase:
    def test_a_fixture_is_found_by_name(self, problem: TwoGeneratorProblem) -> None:
        """Test a fixture identifier resolves to the input of the fixture."""
        case = resolve_case(problem, "fixture:pair")

        assert case.input_data == [2, 1]
        assert case.origin == FixtureOrigin("pair")

    def test_a_fixture_case_carries_the_description_of_the_fixture(self) -> None:
        """Test the origin of a resolved fixture case holds the description of the fixture."""
        origin = resolve_case(NeedsThreeProblem(), "fixture:three").origin

        assert isinstance(origin, FixtureOrigin)
        assert origin.description == "the smallest reversed input"
        assert origin == FixtureOrigin("three")

    def test_a_size_below_the_minimum_of_the_problem_is_an_error(self) -> None:
        """Test a generated identifier whose size is below the problem's minimum is rejected."""
        with pytest.raises(CaseError, match="at least 3 elements"):
            resolve_case(NeedsThreeProblem(), "generated:random:size=2:seed=1")

    def test_an_unknown_fixture_lists_the_available_ones(
        self, problem: TwoGeneratorProblem
    ) -> None:
        """Test an unknown fixture name is an error that lists the fixtures there are."""
        with pytest.raises(
            CaseError, match=r"No fixture named 'nope'. Available fixtures: empty, pair"
        ):
            resolve_case(problem, "fixture:nope")

    def test_a_generated_case_is_rebuilt_exactly(self, problem: TwoGeneratorProblem) -> None:
        """Test resolving the identifier of a generated case reproduces the case."""
        original = generate_case(problem.generators()[0], size=12, seed=99)

        assert resolve_case(problem, original.identifier) == original

    def test_an_unknown_generator_lists_the_available_ones(
        self, problem: TwoGeneratorProblem
    ) -> None:
        """Test an unknown distribution name is an error that lists the distributions there are."""
        with pytest.raises(
            CaseError,
            match=r"Unknown distribution 'nope'\. Available distributions: random, zeros",
        ):
            resolve_case(problem, "generated:nope:size=1:seed=1")


class TestGenerateCase:
    def test_uses_a_random_generator_seeded_with_the_seed(
        self, problem: TwoGeneratorProblem
    ) -> None:
        """Test the input comes from a random generator seeded with the seed of the case."""
        case = generate_case(problem.generators()[0], size=5, seed=7)

        expected = random.Random(7)
        assert case.input_data == [expected.randrange(100) for _ in range(5)]
        assert case.origin == GeneratedOrigin("random", 7, 5)

    def test_rejects_a_negative_size(self, problem: TwoGeneratorProblem) -> None:
        """Test a negative size is an error."""
        with pytest.raises(CaseError, match="negative"):
            generate_case(problem.generators()[0], size=-1, seed=0)

    def test_the_default_generator_is_the_first(self, problem: TwoGeneratorProblem) -> None:
        """Test the default generator is the first one the problem lists."""
        assert default_generator(problem).name == "random"

    def test_a_problem_without_generators_has_no_default(self) -> None:
        """Test a problem with no generators has no default generator."""
        with pytest.raises(CaseError, match="defines no input distributions"):
            default_generator(NoGeneratorProblem())

    def test_startup_case_is_the_default_generator_at_the_minimum_size(
        self, problem: TwoGeneratorProblem
    ) -> None:
        """Test the startup case is the default generator at size zero."""
        case = startup_case(problem, seed=5)

        assert case.input_data == []
        assert case.identifier == "generated:random:size=0:seed=5"

    def test_startup_case_follows_the_minimum_size_of_the_problem(self) -> None:
        """Test the startup case has as many elements as the problem requires at least."""
        case = startup_case(NeedsThreeProblem(), seed=5)

        assert len(case.input_data) == 3
        assert case.identifier == "generated:random:size=3:seed=5"

    def test_check_sizes_accepts_sizes_at_or_above_the_minimum(self) -> None:
        """Test sizes that reach the minimum size of the problem pass the check."""
        check_sizes(NeedsThreeProblem(), (3, 4))

    def test_check_sizes_names_the_sizes_that_are_too_small(self) -> None:
        """Test sizes below the minimum size are named in the error."""
        with pytest.raises(CaseError, match=r"at least 3 elements, but the sizes include 0, 2"):
            check_sizes(NeedsThreeProblem(), (2, 5, 0))


class TestCasePlan:
    def test_rejects_a_negative_random_case_count(self) -> None:
        """Test a plan cannot ask for a negative number of random cases."""
        with pytest.raises(CaseError, match="case count"):
            CasePlan(random_case_count=-1)

    def test_rejects_a_negative_maximum_size(self) -> None:
        """Test a plan cannot have a negative maximum size."""
        with pytest.raises(CaseError, match="maximum size"):
            CasePlan(maximum_size=-1)


class TestBuildCases:
    def test_fixtures_come_first_then_generated_cases(self, problem: TwoGeneratorProblem) -> None:
        """Test the fixtures are listed first, followed by the requested generated cases."""
        cases = build_cases(problem, CasePlan(random_case_count=4))

        assert [case.identifier for case in cases[:2]] == ["fixture:empty", "fixture:pair"]
        assert all(isinstance(case.origin, GeneratedOrigin) for case in cases[2:])
        assert len(cases) == 6

    def test_the_plan_is_deterministic(self, problem: TwoGeneratorProblem) -> None:
        """Test the same plan builds the same cases every time."""
        plan = CasePlan(random_case_count=10, seed=3)

        assert build_cases(problem, plan) == build_cases(problem, plan)

    def test_the_seed_changes_the_cases(self, problem: TwoGeneratorProblem) -> None:
        """Test plans that differ only in the seed build different cases."""
        first = build_cases(problem, CasePlan(random_case_count=10, seed=3))
        second = build_cases(problem, CasePlan(random_case_count=10, seed=4))

        assert first != second

    def test_generators_take_turns_and_shift_by_one_every_round(
        self, problem: TwoGeneratorProblem
    ) -> None:
        """Test generators alternate, starting one place further along in every round."""
        cases = build_cases(problem, CasePlan(include_fixtures=False, random_case_count=6))

        names = [get_generated_origin(case).generator_name for case in cases]

        assert names == ["random", "zeros", "zeros", "random", "random", "zeros"]

    @pytest.mark.parametrize("generator_count", [2, 3, 4])
    def test_every_generator_covers_the_whole_range_of_sizes(self, generator_count: int) -> None:
        """Test each generator gets small and large sizes, and their largest sizes are close."""
        problem = build_many_generator_problem(generator_count)
        plan = CasePlan(include_fixtures=False, random_case_count=20, maximum_size=100)
        sizes_by_generator: dict[str, list[int]] = {}

        for case in build_cases(problem, plan):
            origin = get_generated_origin(case)
            sizes_by_generator.setdefault(origin.generator_name, []).append(origin.size)

        assert len(sizes_by_generator) == generator_count
        for sizes in sizes_by_generator.values():
            assert min(sizes) <= 5
            assert max(sizes) >= 50
        largest = [max(sizes) for sizes in sizes_by_generator.values()]
        assert max(largest) - min(largest) <= 30

    def test_named_generators_restrict_the_plan(self, problem: TwoGeneratorProblem) -> None:
        """Test only the generators named in the plan produce cases."""
        plan = CasePlan(include_fixtures=False, random_case_count=3, generator_names=("zeros",))

        names = {get_generated_origin(case).generator_name for case in build_cases(problem, plan)}

        assert names == {"zeros"}

    def test_an_unknown_generator_name_is_an_error(self, problem: TwoGeneratorProblem) -> None:
        """Test a plan that names an unknown distribution is rejected."""
        with pytest.raises(CaseError, match="Unknown distribution 'nope'"):
            build_cases(problem, CasePlan(generator_names=("nope",)))

    def test_no_fixtures_and_no_random_cases_gives_nothing(
        self, problem: TwoGeneratorProblem
    ) -> None:
        """Test a plan without fixtures and without random cases builds no cases."""
        plan = CasePlan(include_fixtures=False, random_case_count=0)

        assert build_cases(problem, plan) == ()

    def test_zero_random_cases_needs_no_generators(self) -> None:
        """Test a problem without generators still builds its fixtures when no random case is asked."""
        cases = build_cases(NoGeneratorProblem(), CasePlan(random_case_count=0))

        assert len(cases) == 2

    def test_random_cases_without_generators_are_an_error(self) -> None:
        """Test asking for random cases from a problem without generators is an error."""
        with pytest.raises(CaseError, match="defines no input distributions"):
            build_cases(NoGeneratorProblem(), CasePlan())

    def test_sizes_stay_within_bounds_and_favor_small_inputs(
        self, problem: TwoGeneratorProblem
    ) -> None:
        """Test sizes span zero to the maximum, with more than half of them small."""
        plan = CasePlan(include_fixtures=False, random_case_count=40, maximum_size=100, seed=1)

        sizes = [get_generated_origin(case).size for case in build_cases(problem, plan)]

        assert min(sizes) == 0
        assert max(sizes) <= 100
        assert max(sizes) >= 70
        assert sum(size <= 30 for size in sizes) > len(sizes) / 2

    def test_sizes_start_at_the_minimum_size_of_the_problem(self) -> None:
        """Test generated sizes begin at the minimum size of the problem and respect the maximum."""
        plan = CasePlan(include_fixtures=False, random_case_count=30, maximum_size=20)

        cases = build_cases(NeedsThreeProblem(), plan)

        sizes = [get_generated_origin(case).size for case in cases]
        assert min(sizes) == 3
        assert max(sizes) <= 20

    def test_a_maximum_size_below_the_minimum_size_is_an_error(self) -> None:
        """Test a maximum size under the minimum size of the problem is rejected."""
        with pytest.raises(CaseError, match="maximum size 2 is below the smallest size"):
            build_cases(NeedsThreeProblem(), CasePlan(random_case_count=1, maximum_size=2))

    def test_fixtures_carry_their_descriptions(self) -> None:
        """Test the origin of a fixture case holds the description of the fixture."""
        (case,) = build_cases(NeedsThreeProblem(), CasePlan(random_case_count=0))

        assert isinstance(case.origin, FixtureOrigin)
        assert case.origin.description == "the smallest reversed input"

    def test_a_maximum_size_of_zero_gives_only_empty_inputs(
        self, problem: TwoGeneratorProblem
    ) -> None:
        """Test a maximum size of zero makes every generated input empty."""
        plan = CasePlan(include_fixtures=False, random_case_count=5, maximum_size=0)

        lengths = {len(case.input_data) for case in build_cases(problem, plan)}

        assert lengths == {0}

    def test_every_generated_case_can_be_rebuilt_from_its_identifier(
        self, problem: TwoGeneratorProblem
    ) -> None:
        """Test resolving the identifier of each planned case reproduces the case."""
        cases = build_cases(problem, CasePlan(random_case_count=8, seed=2))

        rebuilt = [resolve_case(problem, case.identifier) for case in cases]

        assert rebuilt == list(cases)


class TestHooksThatRaise:
    @pytest.mark.parametrize(
        "call",
        [
            lambda problem: build_cases(problem, CasePlan(random_case_count=0)),
            lambda problem: resolve_case(problem, "fixture:first"),
            lambda problem: problem_fixtures(problem),
        ],
        ids=["build_cases", "resolve_case", "problem_fixtures"],
    )
    def test_fixtures_that_raise_are_a_hook_error_naming_the_hook(
        self, call: Callable[[Problem], object]
    ) -> None:
        """Test an error from the fixtures hook is reported as an error naming the hook."""
        problem = ExplodingFixturesProblem()

        with pytest.raises(HookError, match="The problem's fixtures hook raised RuntimeError"):
            call(problem)

    @pytest.mark.parametrize(
        "call",
        [
            lambda problem: select_generators(problem, ()),
            lambda problem: problem_generators(problem),
            lambda problem: default_generator(problem),
            lambda problem: startup_case(problem, 0),
            lambda problem: build_cases(problem, CasePlan(include_fixtures=False)),
            lambda problem: resolve_case(problem, "generated:random:size=3:seed=1"),
        ],
        ids=[
            "select_generators",
            "problem_generators",
            "default_generator",
            "startup_case",
            "build_cases",
            "resolve_case",
        ],
    )
    def test_a_generators_hook_that_raises_is_a_hook_error_everywhere_it_is_used(
        self, call: Callable[[Problem], object]
    ) -> None:
        """Test an error from the generators hook is reported as an error naming the hook."""
        problem = ExplodingGeneratorsProblem()

        with pytest.raises(HookError, match="The problem's generators hook raised"):
            call(problem)

    @pytest.mark.parametrize(
        "call",
        [
            lambda problem: resolve_case(problem, "generated:broken:size=3:seed=1"),
            lambda problem: build_cases(problem, CasePlan(include_fixtures=False)),
        ],
        ids=["resolve_case", "build_cases"],
    )
    def test_the_function_of_a_generator_that_raises_names_the_generator(
        self, call: Callable[[Problem], object]
    ) -> None:
        """Test an error from a generator function is reported as an error naming the generator."""
        problem = ExplodingGeneratorProblem()

        with pytest.raises(
            HookError,
            match=r"^The problem's 'broken' generator hook raised RuntimeError: generator exploded\.$",
        ):
            call(problem)

    def test_a_working_generator_is_unaffected_by_a_broken_one(self) -> None:
        """Test a generator that works still generates when another generator of the problem raises."""
        problem = ExplodingGeneratorProblem()

        case = resolve_case(problem, "generated:fine:size=3:seed=1")

        assert case.input_data == [0, 0, 0]

    def test_a_fixture_that_is_not_a_fixture_is_a_hook_error(self) -> None:
        """Test a fixtures hook that yields something other than fixtures is a hook error."""
        with pytest.raises(HookError, match=r"fixtures hook raised TypeError.*tuple.*Fixture"):
            problem_fixtures(WrongKindsProblem())

    def test_a_generator_that_is_not_a_generator_is_a_hook_error(self) -> None:
        """Test a generators hook that returns something other than generators is a hook error."""
        with pytest.raises(
            HookError, match=r"generators hook raised TypeError.*str.*InputGenerator"
        ):
            problem_generators(WrongKindsProblem())

    def test_an_error_of_the_caller_is_still_a_case_error(
        self, problem: TwoGeneratorProblem
    ) -> None:
        """Test asking for an unknown distribution is a case error, not a hook error."""
        with pytest.raises(CaseError, match="Unknown distribution 'nope'"):
            select_generators(problem, ("nope",))
