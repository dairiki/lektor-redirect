import hashlib
import posixpath
import re
import sys
import weakref
from collections import defaultdict, deque
from collections.abc import Mapping
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import urljoin

from lektor.build_programs import BuildProgram
from lektor.context import get_ctx
from lektor.db import Page, Record
from lektor.pluginsystem import get_plugin, Plugin
from lektor.reporter import reporter
from lektor.sourceobj import VirtualSourceObject

# FIXME: this is currently broken if alts are enabled

DEFAULT_TEMPLATE = "redirect.html"
DEFAULT_REDIRECT_FROM_FIELD = "redirect_from"


class _VirtualSourceBase(VirtualSourceObject):
    url_path = None  # override inherited property

    def __init__(self, record, url_path):
        super().__init__(record)
        self.url_path = url_path

    @property
    def path(self):
        return f"{self.record.path}" f"@{self.VPATH_PREFIX}{self.url_path.rstrip('/')}"

    def __eq__(self, other):
        if isinstance(other, _VirtualSourceBase):
            return self.path == other.path
        return NotImplemented

    def __hash__(self):
        return hash(self.path)

    def __repr__(self):
        return f"{self.__class__.__name__}({self.record!r}, {self.url_path!r})"

    @classmethod
    def declare_vpath_resolver(cls, env):
        env.virtualpathresolver(cls.VPATH_PREFIX)(cls._vpath_resolver)

    @classmethod
    def _vpath_resolver(cls, record, pieces):
        url_path = "/" + "/".join(pieces)
        if "." not in pieces[-1]:
            url_path += "/"
        return cls(record, url_path)


class Redirect(_VirtualSourceBase):
    VPATH_PREFIX = "redirect"

    @property
    def target(self):
        """The target record of the redirect."""
        return self.record


_HASH_BYTES = (sys.hash_info.width + 7) // 8


class RedirectMap(_VirtualSourceBase):
    VPATH_PREFIX = "redirect-map"

    def get_redirect_map(self):
        pad = self.record.pad
        plugin = get_plugin(RedirectPlugin, env=pad.env)
        index = plugin.get_index(pad)
        return sorted(index.iter_redirect_map())

    def get_checksum(self, path_cache):
        h = hashlib.md5()
        for from_url, to_url in self.get_redirect_map():
            h.update(f"{from_url}\0{to_url}\0".encode())
        return h.hexdigest()


HTML_EXTS = {".html", ".htm"}


class RedirectBuildProgram(BuildProgram):
    def produce_artifacts(self):
        source = self.source

        artifact_name = source.url_path
        if artifact_name.endswith("/"):
            artifact_name += "index.html"
        elif posixpath.splitext(artifact_name)[1].lower() not in HTML_EXTS:
            artifact_name += "/index.html"

        sources = list(source.record.iter_source_filenames())

        self.declare_artifact(artifact_name, sources=sources)

    def build_artifact(self, artifact):
        source = self.source
        plugin = get_plugin(RedirectPlugin, env=self.build_state.env)
        template = plugin.redirect_template
        values = {"target": source.target}
        artifact.render_template_into(template, this=source, values=values)


class RedirectMapBuildProgram(BuildProgram):
    def produce_artifacts(self):
        source = self.source
        artifact_name = source.url_path
        sources = list(source.record.iter_source_filenames())
        self.declare_artifact(artifact_name, sources=sources)

    def build_artifact(self, artifact):
        q = _nginx_escape
        base_path = self.build_state.config.base_path

        def abs_url(url_path):
            return urljoin(base_path, url_path.lstrip("/"))

        with artifact.open("w") as fp:
            for from_url, to_url in self.source.get_redirect_map():
                print(f"{q(abs_url(from_url))} {q(abs_url(to_url))};", file=fp)


class RedirectIndex(Mapping):
    def __init__(self, pad, redirect_from_field=DEFAULT_REDIRECT_FROM_FIELD):
        redirects = defaultdict(set)
        records_by_url = {}

        for record in walk_records(pad):
            for url_path in iter_redirect_urls(record, redirect_from_field):
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

    def __getitem__(self, key, /):
        targets = self._redirects[key]
        assert len(targets) > 0
        return targets[0]

    def __len__(self):
        return len(self._redirects)

    def __iter__(self):
        return iter(self._redirects)

    def check_for_conflict(self, url_path, target):
        existing = self._records_by_url.get(url_path)
        if existing is None:
            pad = target.pad
            with disable_redirect_resolution():
                existing = pad.resolve_url_path(url_path)
        if existing is not None:
            self._report_conflict(url_path, target, existing)
            return True

        for conflict in self._redirects.get(url_path, ()):
            if conflict != target:
                self._report_conflict(url_path, target, conflict)
                return True

        return False

    @staticmethod
    def _report_conflict(url_path, target, conflict):
        reporter.report_generic(
            f"REDIRECT CONFLICT {url_path!r} => {target!r} vs {conflict!r}"
        )

    def iter_redirect_map(self):
        for url_path, target in self.items():
            self.check_for_conflict(url_path, target)
            yield url_path, target.url_path


class RedirectPlugin(Plugin):
    name = "redirect"
    description = "Generate redirects to pages."

    def __init__(self, env, id):
        super().__init__(env, id)
        self._index_cache = weakref.WeakKeyDictionary()

    def get_index(self, pad):
        with suppress(KeyError):
            return self._index_cache[pad]
        self._index_cache[pad] = RedirectIndex(pad, self.redirect_from_field)
        return self._index_cache[pad]

    @property
    def redirect_from_field(self):
        inifile = self.get_config()
        return inifile.get("redirect.redirect_from_field", DEFAULT_REDIRECT_FROM_FIELD)

    @property
    def redirect_template(self):
        inifile = self.get_config()
        return inifile.get("redirect.template", DEFAULT_TEMPLATE)

    @property
    def redirect_map_url(self):
        inifile = self.get_config()
        map_file = inifile.get("redirect.map_file")
        if map_file is None:
            return None
        p = Path(map_file)
        p = p.relative_to(p.anchor)  # remove any drive (windows)
        return "/" + p.as_posix()

    def on_setup_env(self, **extra):
        env = self.env

        alts = env.load_config().list_alternatives()
        if alts:
            msg = "The lektor-redirect plugin currently does not support alts"
            raise RuntimeError(msg)

        env.add_build_program(Redirect, RedirectBuildProgram)
        env.generator(self.generate_redirects)
        Redirect.declare_vpath_resolver(env)

        # XXX: maybe only register if redirect map generation is enabled?
        env.add_build_program(RedirectMap, RedirectMapBuildProgram)
        env.generator(self.generate_redirect_map)
        RedirectMap.declare_vpath_resolver(env)

        env.urlresolver(self.resolve_url)

    def generate_redirects(self, source):
        if not isinstance(source, Record):
            return  # ignore assets

        redirect_from_field = self.redirect_from_field
        index = self.get_index(source.pad)

        redirect_urls = set(iter_redirect_urls(source, redirect_from_field))

        # ignore redirect is to self
        redirect_urls.discard(source.url_path)

        for redirect_url in redirect_urls:
            if index.check_for_conflict(redirect_url, source):
                continue
            yield Redirect(source, redirect_url)

    def generate_redirect_map(self, source):
        if source.path != "/":
            return
        redirect_map_url = self.redirect_map_url
        if redirect_map_url is not None:
            yield RedirectMap(source, redirect_map_url)

    def resolve_url(self, record, url_path):
        if _disable_redirect_resolution.get():
            return None
        index = self.get_index(record.pad)
        url_path = normalize_url_path(record, "/".join(url_path))
        target = index.get(url_path)
        if target is not None:
            return Redirect(target, url_path)
        if record.path == "/" and url_path == self.redirect_map_url:
            return RedirectMap(record, url_path)
        return None


def iter_redirect_urls(record, redirect_from_field=DEFAULT_REDIRECT_FROM_FIELD):
    """Iterate over all redirects requested by record.

    URL paths returned are normalized and absolute.

    """
    try:
        redirect_from = record[redirect_from_field]
    except (TypeError, KeyError):
        pass
    else:
        base = record.parent or record
        for redirect_url in redirect_from:
            yield normalize_url_path(base, redirect_url)


def normalize_url_path(record, url_path):
    """Normalize url_path.

    Returns a normalized, absolute url path.

    If url_path does not start with a /, it is interpreted relative to the url
    of record.

    """
    if not url_path.startswith("/"):
        url_path = posixpath.join(record.url_path, url_path)
    url_path = posixpath.normpath(url_path)
    if "." not in posixpath.basename(url_path):
        url_path += "/"
    return url_path


_disable_redirect_resolution = ContextVar("_disable_redirect_resolution", default=False)


@contextmanager
def disable_redirect_resolution():
    token = _disable_redirect_resolution.set(True)
    try:
        yield
    finally:
        _disable_redirect_resolution.reset(token)


def walk_records(pad):
    # FIXME: use lektorlib to disable dependency tracking

    # We should only be called when filling the RedirectFinder cache, and
    # that should only happen at the beginning of a build-all, so there
    # should not yet be a Context.
    #
    # (It would be possible to deal with being within a context, but we
    # would want to make sure that we don't end up recording dependencies
    # on the entire record tree.)
    assert get_ctx() is None
    records = deque([pad.root])
    while records:
        record = records.popleft()
        if isinstance(record, Page):
            # XXX: Hack around the query API, for the sake of efficiency
            # We could stay within the official API be doing two queries:
            #
            #   records.extend(record.children.include_undiscoverable(True))
            #   records.extend(record.attachments.include_undiscoverable(True))
            #
            # This works, however, and is likely more efficient.
            query = record.children.include_undiscoverable(True)
            query._include_attachments = True
            records.extend(query)
        yield record


def _nginx_escape(str):
    """Escape string, if necessary, for nginx config file."""
    quot = ""
    if re.search(r"[ \"'{};]", str):
        quot = '"'
        if quot in str and "'" not in str:
            quot = "'"

    escaped = re.sub(
        rf"[{quot}$\\]|\A(default|hostnames|include|volatile)\b", r"\\\g<0>", str
    )
    return f"{quot}{escaped}{quot}"
