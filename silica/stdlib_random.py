"""The `random` module: ordinary randomness, and separately, secure randomness.

The distinction is the point of this module, so it is in the names:

* **Ordinary pseudorandom** — `random.float`, `random.int`, `random.choice`,
  `random.shuffle`, `random.seed`. A Mersenne Twister. Fast, reproducible when
  seeded, and **not** suitable for passwords, tokens, keys or anything an attacker
  would like to predict. Nothing here pretends otherwise.
* **Cryptographically secure** — `random.secure_bytes`, `random.secure_int`,
  `random.secure_token`. These use the operating system's CSPRNG through
  `secrets`, are never seeded, and are the ones to use for anything secret.

No capability: this is computation, not access to the machine. A program that can
compute can already generate numbers.

Every function documents its range, and `random.int` is half-open (`low` included,
`high` excluded) to match the rest of the standard library's conventions.
"""

import random as _random
import secrets as _secrets

from .natives import _fail, i64

#: One shared generator, so `random.seed` behaves the way a program expects.
_GENERATOR = _random.Random()

#: A cap on how much randomness one call may ask for, so a typo cannot allocate
#: without limit.
MAX_BYTES = 1024 * 1024


def _type_of(value):
    from .natives import type_name
    return type_name(value)


def _need_int(what, value):
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("%s expects an Int, found %s" % (what, _type_of(value)))
    return value


def _need_bounds(what, low, high):
    _need_int(what, low)
    _need_int(what, high)
    if high <= low:
        _fail("%s needs high > low, found %d and %d" % (what, low, high),
              hint="the range is half-open: low is included, high is not")
    return low, high


def _n_float(ctx, args):
    return _GENERATOR.random()


def _n_int(ctx, args):
    low, high = _need_bounds("random.int", args[0], args[1])
    return i64(_GENERATOR.randrange(low, high))


def _n_choice(ctx, args):
    items = args[0]
    if not isinstance(items, list):
        _fail("random.choice expects a List, found %s" % _type_of(items))
    if not items:
        _fail("random.choice needs a non-empty List",
              hint="there is nothing to choose from")
    return _GENERATOR.choice(items)


def _n_shuffle(ctx, args):
    items = args[0]
    if not isinstance(items, list):
        _fail("random.shuffle expects a List, found %s" % _type_of(items))
    copy = list(items)
    _GENERATOR.shuffle(copy)
    return copy


def _n_seed(ctx, args):
    _GENERATOR.seed(_need_int("random.seed", args[0]))
    return None


def _n_secure_bytes(ctx, args):
    """Hex text, because Silica has no byte type: two characters per byte."""
    count = _need_int("random.secure_bytes", args[0])
    if count < 0:
        _fail("random.secure_bytes expects a non-negative count")
    if count > MAX_BYTES:
        _fail("random.secure_bytes refuses more than %d bytes" % MAX_BYTES)
    return _secrets.token_hex(count)


def _n_secure_int(ctx, args):
    low, high = _need_bounds("random.secure_int", args[0], args[1])
    return i64(low + _secrets.randbelow(high - low))


def _n_secure_token(ctx, args):
    count = _need_int("random.secure_token", args[0])
    if count < 1:
        _fail("random.secure_token expects at least one byte")
    if count > MAX_BYTES:
        _fail("random.secure_token refuses more than %d bytes" % MAX_BYTES)
    return _secrets.token_urlsafe(count)


# (name, params, ret, implementation, requires, path_arg, min_args)
FUNCTIONS = (
    # ordinary pseudorandom: never use these for secrets
    ("float", [], "Float", _n_float, None, None, 0),
    ("int", ["Int", "Int"], "Int", _n_int, None, None, 2),
    ("choice", ["List"], "Any", _n_choice, None, None, 1),
    ("shuffle", ["List"], "List", _n_shuffle, None, None, 1),
    ("seed", ["Int"], "Unit", _n_seed, None, None, 1),
    # cryptographically secure: the operating system's CSPRNG
    ("secure_bytes", ["Int"], "String", _n_secure_bytes, None, None, 1),
    ("secure_int", ["Int", "Int"], "Int", _n_secure_int, None, None, 2),
    ("secure_token", ["Int"], "String", _n_secure_token, None, None, 1),
)
