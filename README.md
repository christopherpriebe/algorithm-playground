# algorithm-playground

A learning and benchmarking sandbox for algorithms. `algorithm-playground` is a
Typer-based command-line harness that drives any executable — written in any
language — as long as the executable honors a small, problem-specific binary
I/O contract.

The harness ships three modes:

| Mode        | What it does                                                              |
| ----------- | ------------------------------------------------------------------------- |
| `test`      | Runs a curated set of small fixtures and reports pass / fail per case.    |
| `benchmark` | Runs seeded random inputs at configurable sizes and reports timings.      |
| `debug`     | Steps interactively through an executable's optional state-snapshot trace.|

The bundled `sorting` problem (sort an array of `i32` ascending) is the v1
reference problem. Adding a new problem is a matter of subclassing
`algorithm_playground.core.problem.Problem`, decorating the subclass with
`@register_problem`, and documenting the binary format.

## Quickstart

```sh
git clone https://github.com/christopherpriebe/algorithm-playground.git
cd algorithm-playground
uv sync --extra dev
```

List the registered problems:

```sh
uv run algorithm-playground list
```

Run the reference Python sort against every test fixture:

```sh
uv run algorithm-playground test sorting examples/sorting/python_sort.py
```

Benchmark with a reproducible seed and write a JSON report:

```sh
uv run algorithm-playground benchmark sorting examples/sorting/python_sort.py \
    --seed 42 --sizes 1000,10000,100000 --repetitions 3 \
    --json /tmp/sorting-bench.json
```

Step through a trace (the example writes two snapshots: input and output):

```sh
uv run algorithm-playground debug sorting examples/sorting/python_sort.py \
    --size 16 --seed 7
```

`n` advances, `p` goes back, `g <index>` jumps, `q` quits. Add
`--auto-advance --delay-milliseconds 200` to play the trace back automatically.

## Executable contract

Every executable obeys the same positional contract:

```
<executable> <input_path> <output_path> [<trace_path>]
```

* `argc == 3`: read binary input from `input_path`, write binary output to
  `output_path`. Exit 0 on success.
* `argc == 4`: same, AND write a binary trace stream to `trace_path`. Optional
  — the `debug` command falls back to a static input/output view when no
  trace is produced.

The exact byte layout is **problem-defined**. For sorting, see
[docs/problems/sorting.rst](docs/problems/sorting.rst).

## Reference executables

The repository ships two sorting executables that conform to the contract.
Both use their language's built-in sort; they show the contract, not an
algorithm:

* `examples/sorting/python_sort.py` — wraps `sorted`; writes a two-snapshot
  trace (input and output) to demonstrate the trace format.
* `examples/sorting/c_qsort.c` — wraps libc `qsort`; ignores the optional
  trace path, demonstrating the "trace not supported" fallback.

Build the C example:

```sh
make -C examples/sorting
```

## Developing

```sh
uv run pytest                       # unit + integration tests
uv run ruff check . && uv run ruff format --check .
uv run ty check                     # static type checking
uv run sphinx-build -W -b html docs docs/_build/html
```

## License

MIT. See [LICENSE](LICENSE).
