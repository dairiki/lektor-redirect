from __future__ import annotations

import weakref
from collections import defaultdict
from contextlib import suppress
from pathlib import Path
from typing import Any, Iterator, Mapping, MutableMapping
from urllib.parse import urljoin

from inifile import IniFile
from lektor.builder import Builder
from lektor.db import Pad, Record
from lektor.environment import Environment
from lektor.pluginsystem import get_plugin, Plugin
from lektor.reporter import reporter

from .exceptions import (
    AmbiguousRedirectException,
    InvalidRedirectException,
    RedirectShadowsExistingRecordException,
    RedirectToSelfException,
)
from .sources import Redirect, RedirectMap
from .util import normalize_url_path, walk_records

# FIXME: this is currently broken if alts are enabled

PLUGIN_ID = "redirect"

DEFAULT_REDIRECT_FROM_FIELD = "redirect_from"


class RedirectPlugin(Plugin):  # type: ignore[misc]
    name = "redirect"
    description = "Generate redirects to pages."

    _index_cache: MutableMapping[Pad, RedirectIndex]

    def __init__(self, env: Environment, id: str):
        super().__init__(env, id)
        self._index_cache = weakref.WeakKeyDictionary()

    def get_index(self, pad: Pad) -> RedirectIndex:
        with suppress(KeyError):
            return self._index_cache[pad]
        self._index_cache[pad] = RedirectIndex(pad)
        return self._index_cache[pad]

    @property
    def redirect_from_field(self) -> str:
        inifile: IniFile = self.get_config()
        return inifile.get("redirect.redirect_from_field", DEFAULT_REDIRECT_FROM_FIELD)

    @property
    def redirect_template(self) -> str | None:
        inifile: IniFile = self.get_config()
        return inifile.get("redirect.template")

    @property
    def redirect_map_url(self) -> str | None:
        inifile: IniFile = self.get_config()
        map_file = inifile.get("redirect.map_file")
        if map_file is None:
            return None
        p = Path(map_file)
        p = p.relative_to(p.anchor)  # remove any drive (windows)
        return "/" + p.as_posix()

    def _get_redirect_urls(self, record: Record) -> set[str]:
        """Get redirects requested by record.

        URL paths returned are normalized and absolute.

        No checking for conflicting redirects is done.
        """
        try:
            redirect_from = record[self.redirect_from_field]
        except (TypeError, KeyError):
            return set()

        base = record.parent or record
        return {
            normalize_url_path(base, redirect_url) for redirect_url in redirect_from
        }

    def get_redirect_urls(self, record: Record) -> set[str]:
        """Get redirects requested by record.

        URL paths returned are normalized and absolute.
        Conflicting redirects are omitted from the results.
        Warnings are logged for any detected conflicting redirect.
        """
        redirect_urls = self._get_redirect_urls(record)
        if len(redirect_urls) == 0:
            return redirect_urls

        index = self.get_index(record.pad)
        return {
            redirect_url
            for redirect_url in self._get_redirect_urls(record)
            if not index.is_conflict(redirect_url, record, warn_on_conflict=True)
        }

    def iter_redirect_map(self, pad: Pad) -> Iterator[tuple[str, str]]:
        base_path: str = pad.db.config.base_path

        def abs_url(url_path: str) -> str:
            return urljoin(base_path, url_path.lstrip("/"))

        index = RedirectIndex(pad)
        for redirect_url in sorted(index):
            target = index[redirect_url]
            if not index.is_conflict(redirect_url, target, warn_on_conflict=True):
                yield abs_url(redirect_url), abs_url(target.url_path)

    def on_setup_env(self, **extra: Any) -> None:
        self._ensure_alts_disabled()
        Redirect._setup_env(self.env)
        # XXX: maybe only register if redirect map generation is enabled?
        RedirectMap._setup_env(self.env)

    def on_before_build_all(self, builder: Builder, **extra: None) -> None:
        self._ensure_alts_disabled()

    def _ensure_alts_disabled(self) -> None:
        env = self.env
        alts = env.load_config().list_alternatives()
        if alts:
            msg = f"The {self.name} plugin currently does not support alts"
            raise RuntimeError(msg)


class RedirectIndex(Mapping[str, Record]):
    def __init__(self, pad: Pad) -> None:
        plugin = get_plugin("redirect", env=pad.env)  # FIXME: abstract
        redirects = defaultdict(set)
        records_by_url = {}

        for record in walk_records(pad):
            for url_path in plugin._get_redirect_urls(record):
                redirects[url_path].add(record)
            records_by_url[record.url_path] = record

        # ignore redirects to self
        for url_path, record in records_by_url.items():
            redirects[url_path].discard(record)

        self._redirects = {
            url_path: list(targets)
            for url_path, targets in redirects.items()
            if len(targets) > 0
        }
        self._records_by_url = records_by_url

    def __getitem__(self, key: str, /) -> Record:
        targets = self._redirects[key]
        assert len(targets) > 0
        return targets[0]

    def __len__(self) -> int:
        return len(self._redirects)

    def __iter__(self) -> Iterator[str]:
        return iter(self._redirects)

    def raise_on_conflict(self, url_path: str, target: Record) -> None:
        if target.url_path == url_path:
            raise RedirectToSelfException(url_path, target)

        existing = self._records_by_url.get(url_path)
        if existing is None:
            pad = target.pad
            with Redirect.disable_url_resolution():
                existing = pad.resolve_url_path(url_path)
        if existing is not None:
            raise RedirectShadowsExistingRecordException(url_path, target, existing)

        for conflict in self._redirects.get(url_path, ()):
            if conflict != target:
                raise AmbiguousRedirectException(url_path, target, conflict)

    def is_conflict(
        self, url_path: str, target: Record, warn_on_conflict: bool = True
    ) -> bool:
        """Check if redirect conflicts with another declared redirect.

        If there is no conflict, returns `False`.

        If the redirect is ambiguous, or conflicts with another record, a warning
        is issued via Lektor's reporter, and `True` is returned.

        """
        try:
            self.raise_on_conflict(url_path, target)
        except RedirectToSelfException as ex:
            if warn_on_conflict and reporter.verbosity >= 1:
                reporter.report_generic(f"Ignoring redirect: {ex}")
            return True
        except InvalidRedirectException as ex:
            if warn_on_conflict:
                reporter.report_generic(f"Invalid redirect: {ex}")
            return True
        else:
            return False
