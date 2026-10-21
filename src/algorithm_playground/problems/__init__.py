"""Built-in problems package.

Importing this package triggers each built-in subpackage to register itself
in :data:`algorithm_playground.core.registry.REGISTRY` via the
``@register_problem`` decorator on the concrete ``Problem`` subclass.
"""

from algorithm_playground.problems import sorting as _sorting  # noqa: F401

__all__: list[str] = []
