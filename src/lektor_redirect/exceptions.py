class InvalidRedirectException(Exception):
    """Exception raised when invalid an redirect is detected."""

    @property
    def url_path(self):
        return self.args[0]

    @property
    def target(self):
        return self.args[1]

    def message(self):
        return f"{self.url_path!r} => {self.target!r}: {self.reason}"

    __str__ = message


class RedirectToSelfException(InvalidRedirectException):
    """Record redirects to self."""

    reason = "redirect to self"


class ConflictingRedirectException(InvalidRedirectException):
    """Redirect conflicts with another record or redirect."""

    @property
    def conflict(self):
        return self.args[2]


class RedirectShadowsExistingRecordException(ConflictingRedirectException):
    """A redirect URL matches the URL of an existing Page or Attachment."""

    @property
    def reason(self):
        return f"redirect url conflicts with existing record {self.conflict!r}"


class RedirectConflictException(ConflictingRedirectException):
    """Multiple records declare a redirect from the same URL."""

    @property
    def reason(self):
        return f"conflicts with redirect {self.url_path!r} => {self.conflict!r}"
