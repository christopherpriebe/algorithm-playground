"""Sphinx configuration for the algorithm-playground documentation."""

from __future__ import annotations

import importlib.metadata

project = "algorithm-playground"
author = "Christopher Priebe"
copyright = "2026, Christopher Priebe"

try:
    release = importlib.metadata.version("algorithm-playground")
except importlib.metadata.PackageNotFoundError:
    release = "0.0.0+local"

version = release

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx_autodoc_typehints",
    "sphinx_copybutton",
    "myst_parser",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "furo"
html_static_path: list[str] = []
html_title = f"{project} {release}"

autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
    "member-order": "bysource",
}
autodoc_typehints = "description"
autodoc_class_signature = "separated"

napoleon_google_docstring = True
napoleon_numpy_docstring = False

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

myst_enable_extensions = [
    "colon_fence",
    "deflist",
]
