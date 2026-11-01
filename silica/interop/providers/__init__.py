"""Concrete providers.

Only one exists: the Python worker, which runs foreign code in a separate
process. The package is deliberately thin — a provider is an adapter over the
interfaces in `silica/interop/`.
"""

from .python_worker import PythonWorkerProvider

__all__ = ["PythonWorkerProvider"]
