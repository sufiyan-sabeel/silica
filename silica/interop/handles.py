"""Opaque foreign handles: identity, ownership and lifetime.

A Silica program never sees an address, a file descriptor or a native handle
integer. It sees a random token that names one object owned by one provider
inside one session. Every use is validated before the provider sees it, and a
released token is refused rather than silently resolving to null.
"""

import secrets

from .errors import InteropError

#: 128 random bits. Not a table index: it leaks nothing and cannot be guessed
#: into another session.
TOKEN_BYTES = 16


class ForeignHandle(object):
    """One foreign object. Created only by `HandleRegistry.create`."""

    __slots__ = ("token", "provider", "kind", "generation", "released")

    def __init__(self, token, provider, kind, generation=1):
        self.token = token
        self.provider = provider
        self.kind = kind
        self.generation = generation
        self.released = False

    def describe(self):
        """A description that never includes the token."""
        return "handle(%s from %s)" % (self.kind, self.provider)

    def __repr__(self):
        return "ForeignHandle(%s)" % self.describe()


class _Record(object):
    __slots__ = ("handle", "provider", "session")

    def __init__(self, handle, provider, session):
        self.handle = handle
        self.provider = provider
        self.session = session


class HandleRegistry(object):
    """Owns every live handle and validates each use."""

    #: How many released tokens are remembered, so "released" can be reported
    #: accurately instead of "unknown". Bounded: a long session cannot grow this
    #: without limit.
    RELEASED_MEMORY = 4096

    def __init__(self, max_handles=1024):
        self.max_handles = max_handles
        self._records = {}
        self._released = {}

    # -- creation ----------------------------------------------------------
    def create(self, provider, kind, session=None):
        if len(self._records) >= self.max_handles:
            raise InteropError(
                "handle.unknown",
                "this session already holds %d handles" % self.max_handles,
                provider=provider,
                hint="release handles explicitly; the limit is per session")
        token = secrets.token_hex(TOKEN_BYTES)
        while token in self._records:          # 128 bits: effectively never
            token = secrets.token_hex(TOKEN_BYTES)
        handle = ForeignHandle(token, provider, kind)
        self._records[token] = _Record(handle, provider, session)
        return handle

    # -- validation --------------------------------------------------------
    def use(self, handle, provider=None, session=None):
        """Return the live handle, or raise.

        Checks, in order: the token exists, it has not been released, and it
        belongs to the provider and session asking for it.
        """
        token = getattr(handle, "token", handle)
        record = self._records.get(token)
        if record is None:
            if token in self._released:
                provider_name, kind = self._released[token]
                raise InteropError(
                    "handle.released",
                    "handle of kind %s was already released" % kind,
                    provider=provider_name,
                    hint="a released handle cannot be used again; create a new one")
            raise InteropError("handle.unknown",
                               "no live handle for that token", provider=provider)
        if record.handle.released:
            raise InteropError(
                "handle.released",
                "handle of kind %s was already released" % record.handle.kind,
                provider=record.provider,
                hint="a released handle cannot be used again; create a new one")
        if provider is not None and record.provider != provider:
            raise InteropError(
                "handle.owner",
                "handle belongs to provider %s, not %s"
                % (record.provider, provider), provider=provider,
                hint="a handle is only usable by the provider that created it")
        if session is not None and record.session is not None \
                and record.session != session:
            raise InteropError("handle.owner",
                               "handle belongs to another session",
                               provider=record.provider)
        return record.handle

    # -- release -----------------------------------------------------------
    def release(self, handle):
        """Release once. Returns True when this call released it.

        Releasing an already-released handle is not an error: it returns False,
        so a cleanup path can be written without tracking what it already did.
        """
        if getattr(handle, "released", False):
            return False
        token = getattr(handle, "token", handle)
        record = self._records.get(token)
        if record is None:
            raise InteropError("handle.unknown", "no live handle for that token")
        if record.handle.released:
            return False
        record.handle.released = True
        record.handle.generation += 1
        del self._records[token]
        self._released[token] = (record.provider, record.handle.kind)
        while len(self._released) > self.RELEASED_MEMORY:
            self._released.pop(next(iter(self._released)))
        return True

    def release_session(self, session):
        """Release every handle a session owns. Returns how many were released."""
        tokens = [token for token, record in self._records.items()
                  if record.session == session]
        for token in tokens:
            self.release(token)
        return len(tokens)

    # -- inspection --------------------------------------------------------
    def live(self, session=None):
        if session is None:
            return len(self._records)
        return sum(1 for record in self._records.values()
                   if record.session == session)

    def stats(self):
        """Counts for a closing summary. Contains no tokens."""
        by_provider = {}
        for record in self._records.values():
            by_provider[record.provider] = by_provider.get(record.provider, 0) + 1
        return {"live": len(self._records), "by_provider": by_provider}
