"""Sphinx configuration."""

import re
from importlib.metadata import version as _version

from docutils.nodes import Element
from sphinx.addnodes import pending_xref
from sphinx.application import Sphinx
from sphinx.environment import BuildEnvironment

project = "algorithm-playground"
author = "Christopher Priebe"
copyright = "2026, Christopher Priebe"
release = _version("algorithm-playground")
version = ".".join(release.split(".")[:2])

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]

exclude_patterns = ["_build"]

autodoc_default_options = {
    "members": True,
    "show-inheritance": True,
}
autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_typehints_description_target = "documented"

napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_use_rtype = False

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "rich": ("https://rich.readthedocs.io/en/stable", None),
}

# Type variables and type aliases have no documentation entries of their own.
nitpick_ignore_regex = [
    ("py:(class|obj)", r"algorithm_playground\..*\.[A-Z][A-Za-z]*T"),
    (
        "py:class",
        r"(algorithm_playground\..*\.)?(AnyProblem|HookResult|ProblemSubclass)",
    ),
]

html_theme = "sphinx_rtd_theme"
html_theme_options = {"navigation_depth": 3}


# Objects live in underscore modules and are documented where their package
# re-exports them. Signatures and base classes still name the private module
# (``algorithm_playground.core._runner.Runner``), so resolve those references
# against the public path (``algorithm_playground.core.Runner``).
_PRIVATE_MODULE = re.compile(r"\._[a-z][a-z_]*(?=\.)")


def _resolve_through_public_package(
    app: Sphinx, env: BuildEnvironment, node: pending_xref, contents: Element
) -> Element | None:
    target = node.get("reftarget", "")
    public_target = _PRIVATE_MODULE.sub("", target)
    if node.get("refdomain") != "py" or public_target == target:
        return None
    return env.get_domain("py").resolve_xref(
        env, node["refdoc"], app.builder, node["reftype"], public_target, node, contents
    )


def setup(app: Sphinx) -> None:
    """Register the resolver for references to private modules."""
    app.connect("missing-reference", _resolve_through_public_package)
