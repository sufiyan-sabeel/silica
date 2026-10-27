"""The Silica capability model.

Silica programs are untrusted by default. A program starts with an **empty**
capability set: it can compute, print and read stdin, and nothing else. Any
privileged operation — reading a file, writing a file, listing a directory —
requires an explicit grant.

Capabilities
------------

Every privileged operation is named by a capability string:

    fs.read     read the contents of a file
    fs.write    create or overwrite a file
    fs.list     list the entries of a directory

A grant is a capability plus a **root**. A root is a filesystem path (a
directory, or a single file) that the capability applies to. A path is only
allowed when it resolves inside one of the roots granted for that capability,
so granting ``data/`` does not grant ``../etc/passwd``.

Granting, denying, inheriting
-----------------------------

* **Granting** happens outside the program: on the command line with
  ``--allow-fs-read DIR`` / ``--allow-fs-write DIR`` / ``--allow-fs-list DIR``,
  or in a TOML file passed to ``--capabilities``. A program cannot grant itself
  anything, because the capability set is built before the VM starts and is
  never reachable from Silica source.
* **Denying** is a separate, stronger action: ``--deny-fs-write`` (or
  ``deny = [...]`` in the TOML file) removes a capability even if a root was
  granted for it. Deny always wins, so a config file can be narrowed safely by
  a caller without editing it.
* **Inheriting**: a Silica run has exactly one capability set, and every
  function called during that run inherits it. ``derive()`` produces a strictly
  narrower set and refuses to widen one, which is the only inheritance
  operation the engine exposes. There is no way for a callee to end up with
  more authority than its caller.

Enforcement
-----------

The check is not written inside the filesystem functions. Each privileged
native declares ``requires=<capability>`` in the native registry, and the VM
authorises the call at the ``CALL_NATIVE`` dispatch point before the native
body runs (see ``VM.run``). A native therefore cannot be reached without
passing through the check, and the resolved path handed to the native is the
one that was authorised — the native never re-resolves it, so a check/use
mismatch cannot occur.
"""

import os

from .errors import CapabilityError, SilicaRuntimeError

FS_READ = "fs.read"
FS_WRITE = "fs.write"
FS_LIST = "fs.list"

KNOWN = (FS_READ, FS_WRITE, FS_LIST)

# which native argument holds the path, per capability, is declared on the
# native itself; this table is only used for diagnostics and config parsing.
_TITLES = {
    FS_READ: "read files",
    FS_WRITE: "write files",
    FS_LIST: "list directories",
}

_FLAGS = {
    FS_READ: "--allow-fs-read",
    FS_WRITE: "--allow-fs-write",
    FS_LIST: "--allow-fs-list",
}


def known_capability(kind):
    return kind in KNOWN


def capability_title(kind):
    return _TITLES.get(kind, kind)


def grant_flag(kind):
    return _FLAGS.get(kind, "--allow-%s" % kind.replace(".", "-"))


class CapabilitySet:
    """An immutable set of capability grants.

    Instances are never mutated; ``grant``, ``deny`` and ``derive`` return new
    sets. That makes it impossible for a native, or a future language feature,
    to widen authority as a side effect of running.
    """

    __slots__ = ("_grants", "_denied", "_base")

    def __init__(self, grants=None, denied=(), base=None):
        self._base = _normalise_root(base if base is not None else os.getcwd())
        resolved = {}
        for kind, roots in (grants or {}).items():
            if kind not in KNOWN:
                raise CapabilityError(
                    "unknown capability '%s'" % kind,
                    hint="known capabilities: %s" % ", ".join(KNOWN))
            resolved[kind] = tuple(_normalise_root(r) for r in roots)
        self._grants = resolved
        self._denied = frozenset(denied)

    # -- construction ---------------------------------------------------------
    @classmethod
    def empty(cls, base=None):
        """The default: no capability is granted."""
        return cls({}, (), base)

    def grant(self, kind, root):
        """Return a new set with ``kind`` granted for ``root``."""
        if kind not in KNOWN:
            raise CapabilityError(
                "unknown capability '%s'" % kind,
                hint="known capabilities: %s" % ", ".join(KNOWN))
        grants = {k: list(v) for k, v in self._grants.items()}
        resolved = self.resolve_root(root)
        roots = grants.setdefault(kind, [])
        if resolved not in roots:
            roots.append(resolved)
        return CapabilitySet(grants, self._denied, self._base)

    def deny(self, kind):
        """Return a new set with ``kind`` denied. Deny overrides any grant."""
        if kind not in KNOWN:
            raise CapabilityError(
                "unknown capability '%s'" % kind,
                hint="known capabilities: %s" % ", ".join(KNOWN))
        return CapabilitySet(self._grants, self._denied | {kind}, self._base)

    def derive(self, grants=None, denied=None):
        """Narrow this set. Never widens: adding a root to a denied kind, or a
        kind that was not granted, is refused rather than silently ignored."""
        narrowed = self
        for kind, root in (grants or {}).items():
            if kind in self._denied:
                raise CapabilityError(
                    "cannot derive '%s': it is denied in this capability set" % kind)
            if kind not in self._grants:
                raise CapabilityError(
                    "cannot derive '%s': it was never granted" % kind,
                    hint="a derived set may only narrow the set it comes from")
            resolved = self.resolve_root(root)
            if resolved not in self._grants[kind]:
                raise CapabilityError(
                    "cannot derive '%s' for %s: that root is not granted" % (kind, resolved),
                    hint="a derived set may only narrow the set it comes from")
            narrowed = narrowed._replace_roots(kind, [resolved])
        for kind in (denied or ()):
            narrowed = narrowed.deny(kind)
        return narrowed

    def _replace_roots(self, kind, roots):
        grants = {k: list(v) for k, v in self._grants.items()}
        grants[kind] = list(roots)
        return CapabilitySet(grants, self._denied, self._base)

    # -- inspection -----------------------------------------------------------
    @property
    def base(self):
        return self._base

    def is_denied(self, kind):
        return kind in self._denied

    def is_granted(self, kind):
        return kind in self._grants and kind not in self._denied

    def roots(self, kind):
        if kind in self._denied:
            return ()
        return self._grants.get(kind, ())

    def grants(self):
        return {k: v for k, v in self._grants.items()}

    def denied(self):
        return sorted(self._denied)

    def is_empty(self):
        return not any(self.roots(k) for k in KNOWN)

    def report(self):
        """Human-readable lines describing the effective set."""
        lines = []
        for kind in KNOWN:
            if kind in self._denied:
                state = "denied"
            elif self._grants.get(kind):
                state = "granted: " + ", ".join(self._grants[kind])
            else:
                state = "not granted"
            lines.append("%-9s %-16s %s" % (kind, capability_title(kind), state))
        return lines

    # -- paths ----------------------------------------------------------------
    def resolve_root(self, root):
        if not isinstance(root, str) or root == "":
            raise CapabilityError(
                "capability root must be a non-empty path",
                hint="pass a directory or file, e.g. --allow-fs-read data")
        return _normalise_root(os.path.join(self._base, root))

    def resolve_path(self, kind, path):
        """Authorise ``path`` for ``kind`` and return its resolved form."""
        if not isinstance(path, str):
            raise SilicaRuntimeError(
                "path must be a String, got %s" % _type_of(path))
        self.require(kind)
        resolved = _normalise_root(os.path.join(self._base, path))
        roots = self._grants.get(kind, ())
        for root in roots:
            if _contains(root, resolved):
                return resolved
        raise CapabilityError(
            "path %r is outside the granted roots for '%s'" % (path, kind),
            hint=_outside_hint(path, roots, kind))

    def require(self, kind):
        if kind in self._denied:
            raise CapabilityError(
                "capability '%s' (%s) is denied for this program"
                % (kind, capability_title(kind)),
                hint="this run explicitly denied it with %s"
                     % grant_flag(kind).replace("--allow-", "--deny-"))
        if not self._grants.get(kind):
            raise CapabilityError(
                "capability '%s' (%s) is not granted"
                % (kind, capability_title(kind)),
                hint="grant it with %s <dir>; Silica grants nothing by default"
                     % grant_flag(kind))

    # -- enforcement ----------------------------------------------------------
    def authorize_call(self, native, args):
        """Authorise a native call at the VM dispatch point.

        Returns the argument list to use, with any path argument replaced by
        the resolved path that was actually authorised.
        """
        kind = native.requires
        self.require(kind)
        index = native.path_arg
        if index is None or index >= len(args):
            return args
        path = args[index]
        if not isinstance(path, str):
            # Not a path at all: let the native raise its own type error rather
            # than reporting a capability problem. No I/O can happen either way.
            return args
        resolved = self.resolve_path(kind, path)
        if resolved == path:
            return args
        updated = list(args)
        updated[index] = resolved
        return updated

    # -- configuration --------------------------------------------------------
    @classmethod
    def from_mapping(cls, data, base=None):
        """Build a set from a parsed TOML ``[capabilities]`` table.

        Accepted shapes (both are equivalent)::

            [capabilities]
            deny = ["fs.write"]
            read = ["data"]        # shorthand: a bare name means fs.<name>

            [capabilities.fs]
            read = ["data"]

            [capabilities]
            "fs.read" = ["data"]
        """
        if data is None:
            return cls.empty(base)
        if not isinstance(data, dict):
            raise CapabilityError(
                "[capabilities] must be a table, found %s" % type(data).__name__)
        grants = {}
        denied = []
        for key, value in data.items():
            if key == "deny":
                denied.extend(_as_kind_list(value, "deny"))
                continue
            if key == "fs" or key == "fs.read" or key == "fs.write" or key == "fs.list":
                if isinstance(value, dict):
                    for sub, roots in value.items():
                        kind = _kind_from_parts("fs", sub)
                        grants.setdefault(kind, []).extend(_as_root_list(roots, kind))
                else:
                    grants.setdefault(key, []).extend(_as_root_list(value, key))
                continue
            if key in ("read", "write", "list"):
                kind = _kind_from_parts("fs", key)
                grants.setdefault(kind, []).extend(_as_root_list(value, kind))
                continue
            raise CapabilityError(
                "unknown key '%s' in [capabilities]" % key,
                hint="known keys: fs (with read/write/list), or fs.read, "
                     "fs.write, fs.list, deny")
        return cls(grants, denied, base)

    @classmethod
    def from_file(cls, path, base=None):
        import tomllib

        try:
            with open(path, "rb") as handle:
                document = tomllib.load(handle)
        except FileNotFoundError:
            raise CapabilityError("no such capability file: %s" % path)
        except OSError as exc:
            raise CapabilityError("cannot read %s: %s" % (path, exc))
        except tomllib.TOMLDecodeError as exc:
            raise CapabilityError(
                "%s is not valid TOML: %s" % (path, exc),
                hint="[capabilities] must be a table of capability grants")
        if "capabilities" not in document:
            raise CapabilityError(
                "%s has no [capabilities] table" % path,
                hint="add [capabilities] with fs.read / fs.write / fs.list")
        return cls.from_mapping(document["capabilities"], base)


# --- helpers -----------------------------------------------------------------
def _type_of(value):
    from .natives import type_name
    return type_name(value)


def _normalise_root(path):
    """Absolute, symlink-resolved form. The tail may not exist yet."""
    return os.path.realpath(os.path.abspath(path))


def _contains(root, path):
    if path == root:
        return True
    prefix = root if root.endswith(os.sep) else root + os.sep
    return path.startswith(prefix)


def _outside_hint(path, roots, kind):
    if not roots:
        return "grant it with %s <dir>; Silica grants nothing by default" % grant_flag(kind)
    listed = ", ".join(roots)
    if ".." in path.replace("\\", "/").split("/"):
        return ("path traversal is not allowed; %r leaves the granted roots (%s)"
                % (path, listed))
    return "granted roots for %s: %s" % (kind, listed)


def _as_root_list(value, kind):
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        raise CapabilityError(
            "capability '%s' must be a list of paths or a single path, found %s"
            % (kind, type(value).__name__))
    for item in value:
        if not isinstance(item, str) or item == "":
            raise CapabilityError(
                "capability '%s' roots must be non-empty strings" % kind)
    return list(value)


def _as_kind_list(value, where):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise CapabilityError(
            "'%s' must be a list of capability names" % where)
    kinds = []
    for item in value:
        if not isinstance(item, str):
            raise CapabilityError("'%s' entries must be strings" % where)
        kinds.append(_normalise_kind(item, where))
    return kinds


def _normalise_kind(name, where):
    if name in KNOWN:
        return name
    if name in ("read", "write", "list"):
        return _kind_from_parts("fs", name)
    raise CapabilityError(
        "unknown capability '%s' in '%s'" % (name, where),
        hint="known capabilities: %s" % ", ".join(KNOWN))


def _kind_from_parts(module, name):
    kind = "%s.%s" % (module, name)
    if kind not in KNOWN:
        raise CapabilityError(
            "unknown capability '%s'" % kind,
            hint="known capabilities: %s" % ", ".join(KNOWN))
    return kind
