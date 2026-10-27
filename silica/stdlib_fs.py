"""The `fs` module: file access behind the capability model.

Every function here declares which capability it needs; the VM authorises the
call before the body runs (see silica/capabilities.py). The path argument has
already been resolved and containment-checked by the time these functions see
it, so they never re-resolve a path and cannot disagree with the check.

Operations, all in the `fs` module (`use fs`):

    fs.read_text(path)          String      requires fs.read
    fs.write_text(path, text)   Unit        requires fs.write
    fs.exists(path)             Bool        requires fs.read
    fs.list_dir(path)           List        requires fs.list

Errors are ordinary located Silica runtime errors. A denial is a capability
error and is raised by the VM, not by this module.
"""

import os

from .capabilities import FS_LIST, FS_READ, FS_WRITE
from .errors import SilicaRuntimeError
from .natives import type_name


def _need_string(name, value):
    if not isinstance(value, str):
        raise SilicaRuntimeError(
            "%s expects a String path, got %s" % (name, type_name(value)))
    return value


def _read_text(ctx, args):
    path = _need_string("fs.read_text", args[0])
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except FileNotFoundError:
        raise SilicaRuntimeError(
            "fs.read_text: no such file: %s" % path,
            hint="check the path, or use fs.exists(path) first")
    except IsADirectoryError:
        raise SilicaRuntimeError(
            "fs.read_text: %s is a directory, not a file" % path,
            hint="use fs.list_dir(path) to list a directory")
    except PermissionError:
        raise SilicaRuntimeError("fs.read_text: permission denied: %s" % path)
    except UnicodeDecodeError as exc:
        raise SilicaRuntimeError(
            "fs.read_text: %s is not valid UTF-8 (byte %d)" % (path, exc.start),
            hint="Silica strings are UTF-8; this file is not text in that encoding")
    except OSError as exc:
        raise SilicaRuntimeError("fs.read_text: %s: %s" % (path, exc.strerror or exc))


def _write_text(ctx, args):
    path = _need_string("fs.write_text", args[0])
    text = args[1]
    if not isinstance(text, str):
        raise SilicaRuntimeError(
            "fs.write_text expects a String as its second argument, got %s"
            % type_name(text))
    try:
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            raise SilicaRuntimeError(
                "fs.write_text: directory does not exist: %s" % parent,
                hint="Silica does not create directories; create it first")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return None
    except IsADirectoryError:
        raise SilicaRuntimeError(
            "fs.write_text: %s is a directory, not a file" % path)
    except PermissionError:
        raise SilicaRuntimeError("fs.write_text: permission denied: %s" % path)
    except OSError as exc:
        raise SilicaRuntimeError("fs.write_text: %s: %s" % (path, exc.strerror or exc))


def _exists(ctx, args):
    path = _need_string("fs.exists", args[0])
    try:
        return os.path.exists(path)
    except OSError as exc:  # pragma: no cover - os.path.exists swallows most
        raise SilicaRuntimeError("fs.exists: %s: %s" % (path, exc.strerror or exc))


def _list_dir(ctx, args):
    path = _need_string("fs.list_dir", args[0])
    try:
        return sorted(os.listdir(path))
    except FileNotFoundError:
        raise SilicaRuntimeError("fs.list_dir: no such directory: %s" % path)
    except NotADirectoryError:
        raise SilicaRuntimeError(
            "fs.list_dir: %s is a file, not a directory" % path,
            hint="use fs.read_text(path) to read a file")
    except PermissionError:
        raise SilicaRuntimeError("fs.list_dir: permission denied: %s" % path)
    except OSError as exc:
        raise SilicaRuntimeError("fs.list_dir: %s: %s" % (path, exc.strerror or exc))


# (name, params, ret, implementation, requires, path_arg, min_args)
FUNCTIONS = (
    ("read_text", ["String"], "String", _read_text, FS_READ, 0, None),
    ("write_text", ["String", "String"], "Unit", _write_text, FS_WRITE, 0, None),
    ("exists", ["String"], "Bool", _exists, FS_READ, 0, None),
    ("list_dir", ["String"], "List", _list_dir, FS_LIST, 0, None),
)
