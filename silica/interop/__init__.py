"""Silica interoperability foundation.

Python-side only. Nothing here is reachable from Silica source: there is no
`use interop`, no new keyword and no new opcode, and the standard-library native
registry is untouched.

The design is in docs/INTEROPERABILITY.md; the audit it rests on is in
docs/INTEROPERABILITY_AUDIT.md. This package implements the parts of that design
that do not execute anything: values, handles, provider metadata, a registry
separate from `silica.natives`, structured errors and the invocation context
whose `authorize` call is the same gate the VM uses for natives.
"""

from .context import InvocationContext
from .errors import CODES, InteropError
from .handles import ForeignHandle, HandleRegistry
from .provider import ABI_VERSION, ForeignType, Provider, Signature
from .registry import ProviderRegistry
from .values import (DEFAULT_LIMITS, INT_MAX, INT_MIN, ForeignValue, Limits, Tag,
                     check_type, from_silica, to_silica)

__all__ = [
    "ABI_VERSION", "CODES", "DEFAULT_LIMITS", "ForeignHandle", "ForeignType",
    "ForeignValue", "HandleRegistry", "INT_MAX", "INT_MIN", "InteropError",
    "InvocationContext", "Limits", "Provider", "ProviderRegistry", "Signature",
    "Tag", "check_type", "from_silica", "to_silica",
]
