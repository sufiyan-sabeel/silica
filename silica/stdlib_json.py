"""The `json` module: JSON parsing and serialisation for the Silica value model.

Silica has six types — String, Int, Float, Bool, List, Map — plus Unit. JSON
maps onto them without inventing anything:

    JSON        Silica
    ----------  -------------------------------------------
    null        Unit
    true/false  Bool (oui / nein)
    number      Int when it is a whole number in 64-bit range, otherwise Float
    string      String (UTF-8; escapes are decoded on parse)
    array       List
    object      Map with String keys

Rules that are stated rather than guessed:

* ``json.parse`` rejects ``NaN``, ``Infinity`` and ``-Infinity``. They are not
  JSON and Silica will not silently accept them.
* An integer literal outside signed 64-bit range is an error, not a silent
  wrap, because ``Int`` is 64-bit.
* A duplicate object key keeps the **last** value, matching what almost every
  JSON reader does. It is documented, not accidental.
* ``json.stringify`` fails on a Map whose keys are not Strings, and on values
  that have no JSON form (an Iterator, for example). It never emits ``NaN``.

Both directions are exercised by round-trip tests.
"""

import json as _json

from .errors import SilicaRuntimeError
from .natives import I64_MAX, I64_MIN, Iterator, type_name

MAX_DEPTH = 200


def _parse_int(text):
    value = int(text, 10)
    if value < I64_MIN or value > I64_MAX:
        raise _OutOfRange(text)
    return value


def _parse_float(text):
    value = float(text)
    if value != value or value in (float("inf"), float("-inf")):
        raise _OutOfRange(text)
    return value


def _reject_constant(text):
    raise _NotJson(text)


class _OutOfRange(Exception):
    def __init__(self, text):
        self.text = text


class _NotJson(Exception):
    def __init__(self, text):
        self.text = text


def _pairs_to_map(pairs):
    result = {}
    for key, value in pairs:
        result[key] = value
    return result


def _n_parse(ctx, args):
    text = args[0]
    if not isinstance(text, str):
        raise SilicaRuntimeError(
            "json.parse expects a String, got %s" % type_name(text))
    try:
        return _json.loads(
            text,
            parse_int=_parse_int,
            parse_float=_parse_float,
            parse_constant=_reject_constant,
            object_pairs_hook=_pairs_to_map,
        )
    except _OutOfRange as exc:
        raise SilicaRuntimeError(
            "json.parse: number %s does not fit in Silica's 64-bit Int or Float"
            % exc.text)
    except _NotJson as exc:
        raise SilicaRuntimeError(
            "json.parse: %s is not valid JSON" % exc.text,
            hint="JSON has no NaN or Infinity")
    except _json.JSONDecodeError as exc:
        raise SilicaRuntimeError(
            "json.parse: invalid JSON at line %d column %d: %s"
            % (exc.lineno, exc.colno, exc.msg),
            hint=_position_hint(text, exc))
    except RecursionError:
        raise SilicaRuntimeError(
            "json.parse: document is nested too deeply (limit %d)" % MAX_DEPTH)


def _position_hint(text, exc):
    lines = text.splitlines()
    if not lines:
        return None
    index = max(0, min(exc.lineno - 1, len(lines) - 1))
    line = lines[index]
    if len(line) > 60:
        return None
    caret = " " * max(0, exc.colno - 1) + "^"
    return "%s\n%s" % (line, caret)


def _n_stringify(ctx, args):
    value = args[0]
    indent = None
    if len(args) > 1:
        indent = args[1]
        if isinstance(indent, bool) or not isinstance(indent, int):
            raise SilicaRuntimeError(
                "json.stringify indent must be an Int, got %s" % type_name(indent))
        if indent < 0 or indent > 8:
            raise SilicaRuntimeError(
                "json.stringify indent must be between 0 and 8, got %d" % indent)
        if indent == 0:
            indent = None
    try:
        return _encode(value, indent, 0)
    except RecursionError:
        raise SilicaRuntimeError(
            "json.stringify: value is nested too deeply (limit %d)" % MAX_DEPTH)


def _encode(value, indent, depth):
    if depth > MAX_DEPTH:
        raise SilicaRuntimeError(
            "json.stringify: value is nested too deeply (limit %d)" % MAX_DEPTH)
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        if value < I64_MIN or value > I64_MAX:
            raise SilicaRuntimeError(
                "json.stringify: %d does not fit in a 64-bit Int" % value)
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise SilicaRuntimeError(
                "json.stringify: NaN and Infinity have no JSON representation",
                hint="check the value before serialising it")
        return repr(float(value))
    if isinstance(value, str):
        return _json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return _encode_list(value, indent, depth)
    if isinstance(value, dict):
        return _encode_map(value, indent, depth)
    if isinstance(value, Iterator):
        raise SilicaRuntimeError(
            "json.stringify: an Iterator has no JSON form",
            hint="build a List from it first")
    raise SilicaRuntimeError(
        "json.stringify: %s has no JSON form" % type_name(value))


def _encode_list(items, indent, depth):
    if not items:
        return "[]"
    parts = [_encode(item, indent, depth + 1) for item in items]
    return _join(parts, "[", "]", indent, depth)


def _encode_map(mapping, indent, depth):
    if not mapping:
        return "{}"
    parts = []
    for key, value in mapping.items():
        if not isinstance(key, str):
            raise SilicaRuntimeError(
                "json.stringify: object keys must be Strings, found %s"
                % type_name(key),
                hint="JSON object keys are always strings")
        parts.append("%s:%s" % (_json.dumps(key, ensure_ascii=False),
                                _encode(value, indent, depth + 1)))
    return _join(parts, "{", "}", indent, depth)


def _join(parts, open_bracket, close_bracket, indent, depth):
    if indent is None:
        return open_bracket + ",".join(parts) + close_bracket
    pad = " " * (indent * (depth + 1))
    closing = " " * (indent * depth)
    return (open_bracket + "\n" + pad
            + (",\n" + pad).join(parts)
            + "\n" + closing + close_bracket)


# (name, params, ret, implementation, requires, path_arg, min_args)
FUNCTIONS = (
    ("parse", ["String"], "Any", _n_parse, None, None, None),
    ("stringify", ["Any", "Int"], "String", _n_stringify, None, None, 1),
)
