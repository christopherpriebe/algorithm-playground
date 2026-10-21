"""Algorithm playground: a learning and benchmarking sandbox for algorithms."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("algorithm-playground")
except PackageNotFoundError:
    __version__ = "0.0.0+local"

__all__ = ["__version__"]
