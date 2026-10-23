Development
===========

Setup
-----

.. code-block:: console

   uv sync
   uv run pre-commit install
   make -C examples/sorting

``uv sync`` installs the package in editable mode with the ``dev`` dependency
group. ``make`` builds the C example; the tests that use it skip without it.

Checks
------

All checks are run through `nox <https://nox.thea.codes>`_:

.. code-block:: console

   uv run nox                    # every default session
   uv run nox -l                 # list sessions
   uv run nox -s tests-3.11       # one Python version
   uv run nox -s tests-3.11 -- -k add   # pass arguments to pytest

==============  ==============================================================
Session         What it does
==============  ==============================================================
``lint``        ``ruff format --check`` and ``ruff check``
``typecheck``   ``ty check`` against every supported Python version
``tests``       pytest on every supported Python version, in parallel, with
                coverage
``coverage``    combines coverage from all ``tests`` runs, writes
                ``htmlcov/``, and fails below the threshold
``docs``        builds these docs with warnings as errors
``build``       builds the sdist and wheel into ``dist/`` (not default)
``bump``        bumps the version (not default)
==============  ==============================================================

Branches
--------

``master`` holds releases only. ``dev`` accumulates feature pull requests,
squash-merged. Feature work happens on ``dev-<name>`` branches cut from
``dev``, and pull requests target ``dev``.

Agents
------

``CLAUDE.md`` is the entry point for Claude Code: commands, the definition of
done, and how work is delegated across model tiers. ``.claude/`` holds per-path
style rules, subagents, skills, hooks, and the permission allowlist, all
committed so every contributor's agent behaves the same.

Releasing
---------

From ``dev``, with a clean tree and nothing on ``master`` that ``dev`` lacks:

.. code-block:: console

   uv run nox -s bump -- minor
   uv run nox
   git commit -am "chore(release): v$(uv version --short)"
   git switch master && git merge --ff-only dev
   git tag -a "v$(uv version --short)" -m "v$(uv version --short)"
   git switch dev
   git push origin dev master --follow-tags

The tag is annotated because ``--follow-tags`` pushes only annotated tags.
Pushing a ``v*`` tag runs the release workflow, which checks that the tag is
on ``master`` and builds the sdist and wheel
and publishes them to PyPI with trusted publishing.
