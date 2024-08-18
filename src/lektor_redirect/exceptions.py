from __future__ import annotations

from typing import Any, Final

from lektor.db import Record


class InvalidRedirectException(Exception):
    """Exception raised when invalid an redirect is detected."""

    def __init__(self, url_path: str, target: Record, *args: Any) -> None:
        super().__init__((url_path, target, *args))
        self.url_path = url_path
        self.target = target

    @property
    def reason(self) -> str:
        raise NotImplementedError

    def message(self) -> str:
        return f"{self.url_path!r} => {self.target!r}: {self.reason}"

    __str__ = message


class RedirectToSelfException(InvalidRedirectException):
    """Record redirects to self."""

    reason: Final = "redirect to self"


class ConflictingRedirectException(InvalidRedirectException):
    """Redirect conflicts with another record or redirect."""

    def __init__(self, url_path: str, target: Record, conflict: Record) -> None:
        super().__init__(url_path, target, conflict)
        self.conflict = conflict


class RedirectShadowsExistingRecordException(ConflictingRedirectException):
    """A redirect URL matches the URL of an existing Page or Attachment."""

    @property
    def reason(self) -> str:
        return f"redirect url conflicts with existing record {self.conflict!r}"


class AmbiguousRedirectException(ConflictingRedirectException):
    """Multiple records declare a redirect from the same URL."""

    @property
    def reason(self) -> str:
        return f"conflicts with redirect {self.url_path!r} => {self.conflict!r}"
