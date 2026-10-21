# algorithm-playground

A learning and benchmarking sandbox for algorithms. `algorithm-playground` is a
Typer-based command-line harness that drives any command — `./sort`,
`python3 sort.py`, `node sort.js`, `java -jar Sort.jar` — written in any
language, as long as it honors a small, problem-specific binary I/O contract.
Several implementations can be tested and benchmarked side by side.

The harness ships three modes:

| Mode        | What it does                                                                  |
| ----------- | ----------------------------------------------------------------------------- |
| `test`      | Runs curated fixtures and seeded random cases; explains and shrinks failures. |
| `benchmark` | Runs seeded random inputs at configurable sizes and compares implementations. |
| `debug`     | Steps interactively, key by key, through an implementation's optional trace. |

The bundled `sorting` problem (sort an array of `i32` ascending) is the v1
reference problem. A problem is an interface: subclass
`algorithm_playground.authoring.Problem`, decorate the subclass with
`@register_problem`, and supply the binary format, some fixtures and input
generators, and a verifier. Seeded random cases, failure reports with the
input, expected output, and actual output, shrinking of failing inputs, and
benchmarking all come from the core. Problems can live in your own package or
solutions repository (see [Write your own problem](#write-your-own-problem)).

## Install

```sh
uv tool install algorithm-playground
# or
pipx install algorithm-playground
```

This puts the `algorithm-playground` command on your path. The `examples/`
directory used below lives only in the
[repository](https://github.com/christopherpriebe/algorithm-playground), not in
the installed package, so clone it to follow along:

```sh
git clone https://github.com/christopherpriebe/algorithm-playground.git
cd algorithm-playground
uv sync --extra dev
```

## Quickstart

The commands below use `uv run` to run `algorithm-playground` from the
checkout; with an installed tool, drop the `uv run` prefix.

List the registered problems, and see what one of them offers (its fixtures,
input distributions, trace support, and counted operations):

```sh
uv run algorithm-playground list
uv run algorithm-playground list sorting
```

Run the reference Python sort against every fixture and 20 seeded random cases:

```sh
uv run algorithm-playground test sorting examples/sorting/python_sort.py
```

When an implementation is wrong, `test` shows the failing input, the expected
and actual output, the smallest failing input that shrinking found, and a
one-line command that reproduces the case; failures that shrink to the same
input are one block, smallest first:

```sh
uv run algorithm-playground test sorting my_sort.py --seed 7 --random-cases 50
uv run algorithm-playground test sorting my_sort.py --case generated:uniform:size=37:seed=1234567
```

`--json report.json` writes everything for CI; `--save-failing-inputs DIRECTORY`
keeps the input of every failing case, and `debug --input-file PATH` steps
through one; `test --help` lists the options.

Benchmark with a reproducible seed and write a JSON report:

```sh
uv run algorithm-playground benchmark sorting examples/sorting/python_sort.py \
    --seed 42 --sizes 1000,10000,100000 --repetitions 3 \
    --json /tmp/sorting-bench.json
```

Benchmarks use the problem's default input distribution (for sorting,
`uniform`). Pass `--distribution` more than once to measure others, such as
`sorted`, `few_unique`, or `median_of_three_killer`, an adversary that makes a
median-of-three quicksort quadratic. With three or more sizes the table ends
each distribution with a `growth` row, the best-fitting class and the fitted
exponent of the median time, for example `~ n log n (n^1.21)`. The growth
subtracts the median startup time of the implementation, so that process startup
does not flatten it (a star marks a series that is still mostly startup);
`--subtract-startup-time` subtracts the mean startup time from the reported
times as well, though the growth does not need it. For example:

```sh
uv run algorithm-playground benchmark sorting my_quicksort.py \
    --distribution uniform --distribution median_of_three_killer \
    --sizes 2000,4000,8000,16000
```

### Compare implementations

`test` and `benchmark` take any number of implementations: file paths, or
command text for anything that is not directly executable (no `chmod +x`
needed). They run on identical inputs and share one table, one plot, and one
JSON report:

```sh
make -C examples/sorting
uv run algorithm-playground test sorting \
    --command "python3 examples/sorting/python_sort.py" examples/sorting/c_qsort
uv run algorithm-playground benchmark sorting \
    examples/sorting/python_sort.py examples/sorting/c_qsort \
    --sizes 1000,10000 --repetitions 3 --reference python_sort.py
```

Each benchmark cell shows the median and the ratio to the reference, for
example `5.620 ms (0.09x)`. An implementation whose build fails is reported
once and left out of the run, and the others still run; one that fails part-way
shows `failed` where it failed and `skipped` for what it never reached. Exit
codes: `0` everything passed, `1` a test, benchmark, or build failed, `2` usage
or configuration error, `130` interrupted with Ctrl-C. Results go to standard
output; errors, warnings, and build output go to standard error.

### Describe implementations in a configuration file

A repository of your own solutions can list its implementations once, in
`algorithm-playground.toml` at its root, and then run them by name (or all at
once when none is named):

```toml
[[implementations]]
name = "merge-sort-c"
problem = "sorting"
command = "./build/merge_sort"
build_command = "make build/merge_sort"    # optional, runs once before use

[[implementations]]
name = "heap-sort-python"
problem = "sorting"
command = "python3 python/heap_sort.py"
environment = { PYTHONPATH = "{configuration_directory}/python/helpers" }  # optional
timeout_seconds = 120                                                      # optional
```

```sh
cd my-solutions                                       # or any directory below it
algorithm-playground test sorting                     # every sorting implementation
algorithm-playground benchmark sorting merge-sort-c heap-sort-python
```

See [docs/configuration.rst](https://github.com/christopherpriebe/algorithm-playground/blob/master/docs/configuration.rst) for every key.

### Write your own problem

A problem does not have to live in this package. Define it in your own
package or in your solutions repository, then make it available with the
configuration file, `--problem-module` (a module name or the path of a `.py`
file), or an entry point:

```toml
# algorithm-playground.toml in your solutions repository
python_paths = ["."]
problem_modules = ["solutions_problems.graphs"]
```

```toml
# or, in a package that provides problems
[project.entry-points."algorithm_playground.problems"]
graphs = "solutions_problems.graphs"
```

Everything a problem needs is exported from `algorithm_playground.authoring`, the
stable module for authors: the interface, readers and writers for the binary
formats (scalars, arrays, records, tagged trace sections), helpers for shrinking
and describing inputs, and a replay of events to the state after each one, so
that a new problem only says what is specific to it. `assert_valid_problem(MyProblem())`
from it checks that a problem satisfies the interface. [docs/writing-a-problem.rst](https://github.com/christopherpriebe/algorithm-playground/blob/master/docs/writing-a-problem.rst)
walks through a complete example, which also lives in
`examples/distinct_count/`.

### Step through a trace

The Python example writes two snapshots (input and output):

```sh
uv run algorithm-playground debug sorting examples/sorting/python_sort.py \
    --size 16 --seed 7
```

On a terminal, right arrow or `n` advances, left arrow or `p` goes back, `g`
jumps to a frame, space pauses auto-advance, and `q` quits (with piped input the
stepper reads one command per line). Add `--auto-advance --delay-milliseconds
200` to play the trace back automatically. A trace may also record events
(compares, swaps, writes): each frame then shows the operation that led to it
with the touched bars colored, and `benchmark --count-operations` reports the
operation counts and their growth per size. The format is in
[docs/problems/sorting.rst](https://github.com/christopherpriebe/algorithm-playground/blob/master/docs/problems/sorting.rst).

## Executable contract

Every implementation is a command (a program plus any leading arguments) to
which the harness appends file paths:

```
<command...> <input_path> <output_path> [<trace_path>]
```

* Two paths: read binary input from `input_path`, write binary output to
  `output_path`. Exit 0 on success.
* Three paths: same, AND write a binary trace stream to `trace_path`. Optional
  — the `debug` command falls back to a static input/output view when no
  trace is produced.

The exact byte layout is **problem-defined**. For sorting, see
[docs/problems/sorting.rst](https://github.com/christopherpriebe/algorithm-playground/blob/master/docs/problems/sorting.rst). The working directory,
environment, and build commands are described in
[docs/executable-contract.rst](https://github.com/christopherpriebe/algorithm-playground/blob/master/docs/executable-contract.rst).

## Reference executables

The repository ships two sorting implementations that conform to the contract.
Both use their language's built-in sort; they show the contract, not an
algorithm:

* `examples/sorting/python_sort.py` — wraps `sorted`; writes a two-snapshot
  trace (input and output) to demonstrate the trace format.
* `examples/sorting/c_qsort.c` — wraps libc `qsort`; ignores the optional
  trace path, demonstrating the "trace not supported" fallback.

`examples/distinct_count/` holds a small problem defined outside the package,
with its own configuration file and an implementation.

Build the C example:

```sh
make -C examples/sorting
```

## Developing

```sh
uv run pytest                       # unit + integration tests, in parallel (pytest-xdist)
uv run pytest -n 0 --pdb            # serially, for debugging a failure
uv run ruff check . && uv run ruff format --check .
uv run ty check                     # static type checking
uv run sphinx-build -W -b html docs docs/_build/html
```

## License

MIT. See [LICENSE](https://github.com/christopherpriebe/algorithm-playground/blob/master/LICENSE).
