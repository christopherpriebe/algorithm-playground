"""Nox sessions for linting, type checking, testing, and docs.

Run ``nox`` for the default sessions, ``nox -l`` to list all sessions, and
``nox -s <name>`` to run one.
"""

import shutil
from pathlib import Path

import nox

nox.options.default_venv_backend = "uv"
nox.options.reuse_venv = "yes"
nox.options.error_on_external_run = True
nox.options.sessions = [
    "lint",
    "typecheck",
    "tests",
    "coverage",
    "docs",
]

ROOT = Path(__file__).parent
PYTHON_VERSIONS = ["3.11", "3.12", "3.13", "3.14", "3.15"]
DEFAULT_PYTHON = PYTHON_VERSIONS[0]


def _sync(session: nox.Session, *groups: str) -> None:
    """Install the locked project and the given dependency groups.

    Args:
        session: The session whose virtualenv is synced.
        *groups: Dependency groups from ``pyproject.toml`` to install.
    """
    session.run_install(
        "uv",
        "sync",
        "--locked",
        "--no-default-groups",
        *(f"--group={group}" for group in groups),
        f"--python={session.virtualenv.location}",
        env={"UV_PROJECT_ENVIRONMENT": session.virtualenv.location},
        external=True,
    )


@nox.session(python=DEFAULT_PYTHON)
def lint(session: nox.Session) -> None:
    """Check formatting and lint rules with ruff."""
    session.run_install(
        "uv",
        "sync",
        "--locked",
        "--only-group=lint",
        f"--python={session.virtualenv.location}",
        env={"UV_PROJECT_ENVIRONMENT": session.virtualenv.location},
        external=True,
    )
    session.run("ruff", "format", "--check", ".")
    session.run("ruff", "check", ".")


@nox.session(python=DEFAULT_PYTHON)
def typecheck(session: nox.Session) -> None:
    """Type check with ty against every supported Python version."""
    _sync(session, "typecheck")
    for version in PYTHON_VERSIONS:
        session.log(f"ty: Python {version}")
        session.run("ty", "check", f"--python-version={version}")


@nox.session(python=PYTHON_VERSIONS)
def tests(session: nox.Session) -> None:
    """Run the test suite in parallel with coverage."""
    _sync(session, "test")
    session.run(
        "pytest",
        "--cov",
        "--cov-report=",
        *session.posargs,
        env={"COVERAGE_FILE": str(ROOT / f".coverage.{session.python}")},
    )


@nox.session(python=DEFAULT_PYTHON)
def coverage(session: nox.Session) -> None:
    """Combine coverage from all test runs and enforce the threshold."""
    _sync(session, "test")
    if any(ROOT.glob(".coverage.*")):
        session.run("coverage", "combine")
    elif not (ROOT / ".coverage").exists():
        session.error("no coverage data; run the tests sessions first")
    session.run("coverage", "html")
    session.run("coverage", "report")


@nox.session(python=DEFAULT_PYTHON)
def docs(session: nox.Session) -> None:
    """Build the Sphinx docs, treating warnings as errors."""
    _sync(session, "docs")
    build_dir = ROOT / "docs" / "_build"
    shutil.rmtree(build_dir, ignore_errors=True)
    session.run(
        "sphinx-build",
        "--fail-on-warning",
        "--keep-going",
        "--nitpicky",
        "--builder=html",
        "docs",
        str(build_dir / "html"),
    )


@nox.session(python=DEFAULT_PYTHON)
def build(session: nox.Session) -> None:
    """Build the sdist and wheel into ``dist/``."""
    shutil.rmtree(ROOT / "dist", ignore_errors=True)
    session.run("uv", "build", external=True)


@nox.session(venv_backend="none")
def bump(session: nox.Session) -> None:
    """Bump the version: ``nox -s bump -- major|minor|patch``."""
    if len(session.posargs) != 1:
        session.error("usage: nox -s bump -- major|minor|patch")
    part = session.posargs[0]
    session.run("uv", "version", "--bump", part, "--no-sync", external=True)
