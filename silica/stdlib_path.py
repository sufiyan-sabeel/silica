"""The `path` module: pure string manipulation of paths.

**No filesystem access, so no capability.** Nothing here opens, stats or lists
anything: these functions split, join and normalise the *text* of a path. That is
the point — a program can reason about paths without being allowed to touch the
disk, and the functions that do touch it (`fs.*`) stay behind `fs.read` /
`fs.write` / `fs.list`.

Two rules stated rather than guessed:

* `path.normalise` is **lexical**. It collapses `//`, `.` and `..` in the text and
  never consults the filesystem, so it cannot know that `a/b/..` is a symlink
  pointing elsewhere. `path.is_within` is therefore a *check*, not a sandbox: the
  real boundary is the capability check in `fs.*`, which resolves and compares
  canonical paths.
* Separators: paths are handled in the host's convention. `path.join` inserts
  `os.sep`; both `/` and `os.sep` are accepted on input.
"""

import os

from .natives import _fail


def _need_string(what, value):
    if not isinstance(value, str):
        _fail("%s expects a String, found %s" % (what, _type_of(value)))
    if "\x00" in value:
        _fail("%s refuses a path containing a NUL byte" % what,
              hint="a NUL cannot appear in a real path")
    return value


def _type_of(value):
    from .natives import type_name
    return type_name(value)


def _n_join(ctx, args):
    parts = args[0]
    if not isinstance(parts, list):
        _fail("path.join expects a List of Strings, found %s" % _type_of(parts))
    if not parts:
        return ""
    cleaned = []
    for index, part in enumerate(parts):
        _need_string("path.join", part)
        if not part:
            continue
        cleaned.append(part)
    if not cleaned:
        return ""
    return os.path.join(*cleaned)


def _n_base(ctx, args):
    return os.path.basename(_need_string("path.base", args[0]))


def _n_dir(ctx, args):
    return os.path.dirname(_need_string("path.dir", args[0]))


def _n_ext(ctx, args):
    return os.path.splitext(_need_string("path.ext", args[0]))[1]


def _n_stem(ctx, args):
    return os.path.splitext(os.path.basename(_need_string("path.stem",
                                                          args[0])))[0]


def _n_split(ctx, args):
    path = _need_string("path.split", args[0])
    head, tail = os.path.split(path)
    return [head, tail]


def _n_normalise(ctx, args):
    path = _need_string("path.normalise", args[0])
    if not path:
        return ""
    # lexical only: `normpath` collapses `.`, `..` and repeated separators in the
    # text and does not touch the filesystem (which is why this needs no grant)
    return os.path.normpath(path)


def _n_is_absolute(ctx, args):
    return os.path.isabs(_need_string("path.is_absolute", args[0]))


def _n_is_within(ctx, args):
    """Lexical containment. See the module docstring: not a sandbox."""
    path = os.path.normpath(_need_string("path.is_within", args[0]))
    root = os.path.normpath(_need_string("path.is_within", args[1]))
    if path == root:
        return True
    if not root.endswith(os.sep):
        root = root + os.sep
    return path.startswith(root)


def _n_absolute(ctx, args):
    """Absolute form of a path, resolved against the current directory.

    Lexical like the rest of this module: no filesystem lookup, no symlink
    resolution. It does not reveal whether the path exists.
    """
    return os.path.abspath(_need_string("path.absolute", args[0]))


def _n_with_suffix(ctx, args):
    path = _need_string("path.with_suffix", args[0])
    suffix = _need_string("path.with_suffix", args[1])
    if suffix and not suffix.startswith("."):
        suffix = "." + suffix
    stem, _old = os.path.splitext(path)
    return stem + suffix


# (name, params, ret, implementation, requires, path_arg, min_args)
FUNCTIONS = (
    ("join", ["List"], "String", _n_join, None, None, 1),
    ("base", ["String"], "String", _n_base, None, None, 1),
    ("dir", ["String"], "String", _n_dir, None, None, 1),
    ("ext", ["String"], "String", _n_ext, None, None, 1),
    ("stem", ["String"], "String", _n_stem, None, None, 1),
    ("split", ["String"], "List", _n_split, None, None, 1),
    ("normalise", ["String"], "String", _n_normalise, None, None, 1),
    ("absolute", ["String"], "String", _n_absolute, None, None, 1),
    ("is_absolute", ["String"], "Bool", _n_is_absolute, None, None, 1),
    ("is_within", ["String", "String"], "Bool", _n_is_within, None, None, 2),
    ("with_suffix", ["String", "String"], "String", _n_with_suffix, None, None, 2),
)

#: `path.sep` — the separator this host uses, so a program need not guess.
CONSTANTS = {"sep": os.sep}
