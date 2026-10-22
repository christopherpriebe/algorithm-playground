"""Tests for the dimensions a problem declares and the sizes made of them."""

import copy
import pickle
import random
from typing import Any, cast

import pytest

from algorithm_playground.core import (
    Case,
    CaseError,
    CasePlan,
    Dimension,
    GeneratedOrigin,
    InputGenerator,
    Size,
    build_cases,
    build_default_maximum_size,
    build_minimum_size,
    build_startup_case,
    check_sizes,
    generate_case,
    get_growth_dimension,
    parse_case_identifier,
    parse_size,
    resolve_case,
)
from algorithm_playground.problems.sorting import SortingProblem
from helpers.two_dimensions import Pair, TwoDimensionProblem

TWO_DIMENSIONS = TwoDimensionProblem.dimensions
ONE_DIMENSION = (Dimension("size"),)


def generate_zeros(_random_generator: random.Random, size: int) -> list[int]:
    """Generate ``size`` zeros, taking the size the way a one-dimension generator does."""
    return [0] * size


@pytest.fixture
def pairs() -> TwoDimensionProblem:
    """A problem with the dimensions vertices (at least one) and edges."""
    return TwoDimensionProblem()


def collect_pairs(problem: TwoDimensionProblem, plan: CasePlan) -> list[Pair]:
    """Build the cases of a plan and return their inputs."""
    return [cast("Case[Pair]", case).input_data for case in build_cases(problem, plan)]


def test_a_dimension_needs_only_a_name() -> None:
    """Test a dimension built from a name alone starts at zero and defaults to a hundred."""
    dimension = Dimension("size")

    assert (dimension.description, dimension.minimum, dimension.default_maximum) == (
        "",
        0,
        100,
    )


@pytest.mark.parametrize(
    "name",
    ["", "has:colon", "has space", "has\ttab", "has=equals", "edge-count", "2d"],
    ids=repr,
)
def test_a_dimension_name_is_a_python_identifier(name: str) -> None:
    """Test a dimension name must be an identifier, since generators receive it as a keyword."""
    with pytest.raises(ValueError, match="identifier"):
        Dimension(name)


@pytest.mark.parametrize("name", ["seed", "random_generator"])
def test_the_names_the_harness_uses_itself_are_not_dimensions(name: str) -> None:
    """Test the seed of a case and the generator's own argument cannot name a dimension."""
    with pytest.raises(ValueError, match=f"'{name}' is reserved"):
        Dimension(name)


@pytest.mark.parametrize("value", ["3", 1.5, True], ids=repr)
def test_a_dimension_minimum_must_be_an_integer(value: object) -> None:
    """Test a minimum that is not an integer, a boolean included, is rejected."""
    with pytest.raises(ValueError, match="integer"):
        Dimension("size", minimum=cast("int", value))


@pytest.mark.parametrize("value", ["3", 1.5, True], ids=repr)
def test_a_dimension_default_maximum_must_be_an_integer(value: object) -> None:
    """Test a default maximum that is not an integer, a boolean included, is rejected."""
    with pytest.raises(ValueError, match="integer"):
        Dimension("size", default_maximum=cast("int", value))


def test_a_dimension_minimum_must_not_be_negative() -> None:
    """Test a negative minimum is rejected."""
    with pytest.raises(ValueError, match="minimum"):
        Dimension("size", minimum=-1)


def test_a_dimension_default_maximum_must_reach_its_minimum() -> None:
    """Test a default maximum below the minimum is rejected."""
    with pytest.raises(ValueError, match="default maximum"):
        Dimension("size", minimum=5, default_maximum=4)


def test_a_size_maps_each_dimension_to_its_value_in_order() -> None:
    """Test a size is a mapping from dimension names to values, in the order given."""
    size = Size(vertices=3, edges=5)

    assert list(size) == ["vertices", "edges"]
    assert (size["vertices"], size["edges"], len(size)) == (3, 5, 2)


def test_a_size_prints_its_dimensions_the_way_identifiers_do() -> None:
    """Test the text of a size is the part of a case identifier that names the dimensions."""
    size = Size(vertices=3, edges=5)

    assert str(size) == "vertices=3:edges=5"
    assert repr(size) == "Size(vertices=3, edges=5)"


def test_sizes_with_the_same_values_are_equal_whatever_their_order() -> None:
    """Test two sizes with the same values are equal and hash alike, in any order."""
    assert Size(vertices=3, edges=5) == Size(edges=5, vertices=3)
    assert len({Size(vertices=3, edges=5), Size(edges=5, vertices=3)}) == 1


def test_a_size_survives_pickling_and_copying() -> None:
    """Test a size comes back equal, in the same order, from a pickle and from a deep copy."""
    size = Size(vertices=3, edges=5)

    unpickled = pickle.loads(pickle.dumps(size))  # noqa: S301  round trip of a value this test built itself

    assert unpickled == size
    assert str(unpickled) == "vertices=3:edges=5"
    assert copy.deepcopy(size) == size


def test_a_size_takes_no_new_attributes() -> None:
    """Test a size is a value: nothing can be attached to it after it is built."""
    size = Size(size=3)

    with pytest.raises(AttributeError):
        size.extra = 1  # ty: ignore[unresolved-attribute]  deliberately attaching an unknown attribute


def test_a_dimension_may_be_called_self() -> None:
    """Test the name ``self`` is an ordinary dimension name."""
    assert Size(self=1)["self"] == 1


def test_a_size_needs_at_least_one_dimension() -> None:
    """Test a size without any dimension is rejected."""
    with pytest.raises(ValueError, match="at least one dimension"):
        Size()


def test_a_size_must_not_be_negative() -> None:
    """Test a negative value is rejected with the name of its dimension."""
    with pytest.raises(ValueError, match=r"'edges'.*negative"):
        Size(vertices=1, edges=-1)


@pytest.mark.parametrize("value", [True, 2.5, "3"], ids=repr)
def test_a_size_holds_integers_only(value: object) -> None:
    """Test a value that is not an integer, a boolean included, is rejected."""
    with pytest.raises(ValueError, match="integer"):
        Size(size=cast("int", value))


def test_a_size_is_parsed_from_one_part_per_dimension() -> None:
    """Test the text of a size parses back to the size."""
    assert parse_size("vertices=3:edges=5", TWO_DIMENSIONS) == Size(vertices=3, edges=5)


def test_a_parsed_size_lists_the_dimensions_in_declared_order() -> None:
    """Test a size given in another order prints in the order the problem declares."""
    size = parse_size("edges=5:vertices=3", TWO_DIMENSIONS)

    assert str(size) == "vertices=3:edges=5"


def test_a_plain_number_is_the_value_of_a_lone_dimension() -> None:
    """Test a problem with one dimension takes a bare number as its size."""
    assert parse_size("7", ONE_DIMENSION) == Size(size=7)


def test_a_plain_number_cannot_stand_for_several_dimensions() -> None:
    """Test a bare number is refused for a problem with several dimensions, with the form to use."""
    with pytest.raises(CaseError, match="vertices=N:edges=N"):
        parse_size("7", TWO_DIMENSIONS)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("vertices=3", "edges"),
        ("vertices=3:edges=5:weight=2", "weight"),
        ("vertices=3:vertices=4", "more than once"),
        ("vertices=03:edges=5", "plain integer"),
        ("vertices=-1:edges=5", "negative"),
        ("", "vertices=N:edges=N"),
    ],
    ids=[
        "missing-dimension",
        "unknown-dimension",
        "repeated-dimension",
        "leading-zero",
        "negative",
        "empty",
    ],
)
def test_a_malformed_size_is_rejected_with_the_reason(text: str, message: str) -> None:
    """Test a size that does not name each dimension once with a plain integer is rejected."""
    with pytest.raises(CaseError, match=message):
        parse_size(text, TWO_DIMENSIONS)


def test_the_problem_has_the_dimensions_it_declares(pairs: TwoDimensionProblem) -> None:
    """Test the dimensions of a problem are the ones its class declares, in order."""
    assert [dimension.name for dimension in pairs.dimensions] == ["vertices", "edges"]


def test_the_growth_dimension_is_the_named_one(pairs: TwoDimensionProblem) -> None:
    """Test the growth dimension is the one the problem names."""
    assert get_growth_dimension(pairs).name == "edges"


def test_the_growth_dimension_is_the_first_unless_named() -> None:
    """Test a problem that names no growth dimension grows along its first one."""
    assert get_growth_dimension(SortingProblem()).name == "size"


def test_the_minimum_size_has_every_dimension_at_its_minimum(
    pairs: TwoDimensionProblem,
) -> None:
    """Test the minimum size of a problem takes the minimum of each dimension."""
    assert build_minimum_size(pairs) == Size(vertices=1, edges=0)


def test_the_default_maximum_size_has_every_dimension_at_its_default_maximum(
    pairs: TwoDimensionProblem,
) -> None:
    """Test the default maximum size of a problem takes the default maximum of each dimension."""
    assert build_default_maximum_size(pairs) == Size(vertices=40, edges=80)


def test_the_startup_case_is_at_the_minimums(pairs: TwoDimensionProblem) -> None:
    """Test the startup case is the default generator at the minimum of every dimension."""
    case = build_startup_case(pairs, seed=5)

    assert case.input_data == (1, 0)
    assert case.identifier == "generated:exact:vertices=1:edges=0:seed=5"


def test_a_generator_receives_every_dimension_by_name(
    pairs: TwoDimensionProblem,
) -> None:
    """Test a generator is called with one keyword argument per dimension."""
    case = generate_case(pairs.generators()[0], size=Size(vertices=3, edges=5), seed=1)

    assert case.input_data == (3, 5)
    assert case.identifier == "generated:exact:vertices=3:edges=5:seed=1"


def test_a_generator_that_takes_a_size_is_called_by_keyword_too() -> None:
    """Test a generator written for one dimension gets its size as the keyword ``size``."""
    generator = InputGenerator("zeros", description="zeros", generate=generate_zeros)

    case = generate_case(generator, size=Size(size=3), seed=0)

    assert case.input_data == [0, 0, 0]


def test_an_identifier_names_every_dimension_before_the_seed() -> None:
    """Test a generated identifier lists one part per dimension and ends in the seed."""
    origin = GeneratedOrigin(
        generator_name="exact", seed=1, size=Size(vertices=3, edges=5)
    )

    assert origin.identifier == "generated:exact:vertices=3:edges=5:seed=1"
    assert parse_case_identifier(origin.identifier) == origin


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("generated:exact:seed=1", "names no dimension"),
        ("generated:exact:vertices=1:vertices=2:seed=1", "more than once"),
        ("generated:exact:vertices=1:edges=2", "no valid 'seed=N' part"),
    ],
    ids=["no-dimension", "repeated-dimension", "no-seed"],
)
def test_a_malformed_identifier_with_dimensions_is_rejected(
    text: str, message: str
) -> None:
    """Test an identifier without a dimension, with one twice, or without a seed is rejected."""
    with pytest.raises(CaseError, match=message):
        parse_case_identifier(text)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("generated:exact:seed=3:seed=4", "reserved"),
        ("generated:exact:bad name=3:seed=4", "identifier"),
    ],
    ids=["seed-as-dimension", "label-not-an-identifier"],
)
def test_an_identifier_with_an_unusable_dimension_label_is_rejected(
    text: str, message: str
) -> None:
    """Test an identifier whose dimension label is reserved or not an identifier is rejected."""
    with pytest.raises(CaseError, match=message):
        parse_case_identifier(text)


def test_a_case_is_rebuilt_whatever_the_order_of_the_dimensions(
    pairs: TwoDimensionProblem,
) -> None:
    """Test an identifier that lists the dimensions in another order rebuilds the same case."""
    case = resolve_case(pairs, "generated:exact:edges=5:vertices=3:seed=1")

    assert case.input_data == (3, 5)
    assert case.identifier == "generated:exact:vertices=3:edges=5:seed=1"


def test_an_identifier_with_the_wrong_dimensions_is_an_error(
    pairs: TwoDimensionProblem,
) -> None:
    """Test an identifier that names other dimensions than the problem's is rejected."""
    with pytest.raises(CaseError, match="has the dimensions vertices, edges"):
        resolve_case(pairs, "generated:exact:size=3:seed=1")


def test_an_identifier_with_a_dimension_the_problem_lacks_is_an_error() -> None:
    """Test an identifier naming a dimension that a one-dimension problem lacks is rejected."""
    with pytest.raises(CaseError, match="has the dimensions size"):
        resolve_case(SortingProblem(), "generated:uniform:vertices=3:seed=1")


def test_sizes_at_or_above_every_minimum_pass_the_check(
    pairs: TwoDimensionProblem,
) -> None:
    """Test sizes that reach the minimum of every dimension pass the check."""
    check_sizes(pairs, (Size(vertices=1, edges=0), Size(vertices=5, edges=9)))


def test_a_size_below_the_minimum_of_a_dimension_names_it(
    pairs: TwoDimensionProblem,
) -> None:
    """Test a size below the minimum of a dimension is named with the dimension."""
    with pytest.raises(
        CaseError, match=r"'vertices' of at least 1.*vertices=0:edges=3"
    ):
        check_sizes(pairs, (Size(vertices=0, edges=3),))


def test_a_size_with_other_dimensions_is_refused(pairs: TwoDimensionProblem) -> None:
    """Test a size that names other dimensions than the problem's is refused."""
    with pytest.raises(CaseError, match="has the dimensions vertices, edges"):
        check_sizes(pairs, (Size(size=3),))


def test_a_plan_covers_every_dimension_from_its_minimum_to_its_default_maximum(
    pairs: TwoDimensionProblem,
) -> None:
    """Test generated cases span each dimension from its minimum up to its default maximum."""
    plan = CasePlan(include_fixtures=False, random_case_count=20, seed=1)

    generated = collect_pairs(pairs, plan)

    vertices = [pair[0] for pair in generated]
    edges = [pair[1] for pair in generated]
    assert 1 <= min(vertices) <= 3
    assert 20 <= max(vertices) <= 40
    assert 0 <= min(edges) <= 5
    assert 40 <= max(edges) <= 80


def test_the_dimensions_of_a_plan_vary_independently(
    pairs: TwoDimensionProblem,
) -> None:
    """Test the edges of the generated cases do not simply grow with their vertices."""
    plan = CasePlan(include_fixtures=False, random_case_count=20, seed=1)

    generated = collect_pairs(pairs, plan)

    edges_in_vertex_order = [pair[1] for pair in sorted(generated)]
    assert edges_in_vertex_order != sorted(edges_in_vertex_order)


def test_a_plan_takes_a_maximum_for_every_dimension(
    pairs: TwoDimensionProblem,
) -> None:
    """Test a maximum size caps each dimension at the value given for it."""
    plan = CasePlan(
        include_fixtures=False,
        random_case_count=20,
        maximum_size=Size(vertices=5, edges=10),
        seed=2,
    )

    generated = collect_pairs(pairs, plan)

    assert all(1 <= vertices <= 5 and 0 <= edges <= 10 for vertices, edges in generated)
    assert max(pair[0] for pair in generated) >= 3
    assert max(pair[1] for pair in generated) >= 5


def test_a_maximum_with_other_dimensions_is_an_error(
    pairs: TwoDimensionProblem,
) -> None:
    """Test a maximum size that names other dimensions than the problem's is rejected."""
    with pytest.raises(CaseError, match="has the dimensions vertices, edges"):
        build_cases(pairs, CasePlan(random_case_count=1, maximum_size=Size(size=5)))


def test_a_maximum_below_the_minimum_of_a_dimension_names_it(
    pairs: TwoDimensionProblem,
) -> None:
    """Test a maximum below the minimum of a dimension is rejected with the dimension."""
    plan = CasePlan(random_case_count=1, maximum_size=Size(vertices=0, edges=10))

    with pytest.raises(CaseError, match=r"below the smallest.*'vertices'"):
        build_cases(pairs, plan)


def test_every_planned_case_can_be_rebuilt_from_its_identifier(
    pairs: TwoDimensionProblem,
) -> None:
    """Test resolving the identifier of each planned case reproduces the case."""
    cases = build_cases(pairs, CasePlan(random_case_count=6, seed=3))

    rebuilt: list[Any] = [resolve_case(pairs, case.identifier) for case in cases]

    assert rebuilt == list(cases)
