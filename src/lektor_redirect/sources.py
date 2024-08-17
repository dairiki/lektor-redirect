import hashlib
import posixpath
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from functools import cached_property

from lektor.build_programs import BuildProgram
from lektor.db import Record
from lektor.pluginsystem import get_plugin
from lektor.sourceobj import VirtualSourceObject

from .util import nginx_quote_for_map, normalize_url_path

HTML_EXTS = {".html", ".htm"}


def _get_redirect_plugin(env):
    from .plugin import RedirectPlugin  # FIXME: circ dep

    return get_plugin(RedirectPlugin, env)


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
    def _setup_env(cls, env):
        env.add_build_program(cls, cls.BuildProgram)
        env.generator(cls._generator)
        env.virtualpathresolver(cls.VPATH_PREFIX)(cls._vpath_resolver)
        env.urlresolver(cls._resolve_url)

    @classmethod
    def _vpath_resolver(cls, record, pieces):
        url_path = "/" + "/".join(pieces)
        if "." not in pieces[-1]:
            url_path += "/"
        return cls(record, url_path)

    @classmethod
    def _generator(cls, source):
        raise NotImplementedError

    @classmethod
    def _resolve_url(cls, record, url_path):
        raise NotImplementedError


class Redirect(_VirtualSourceBase):
    VPATH_PREFIX = "redirect"

    @property
    def target(self):
        """The target record of the redirect."""
        return self.record

    _disable_url_resolution = ContextVar(
        f"{__qualname__}._disable_url_resolution", default=False
    )

    @classmethod
    @contextmanager
    def disable_url_resolution(cls):
        token = cls._disable_url_resolution.set(True)
        try:
            yield
        finally:
            cls._disable_url_resolution.reset(token)

    @classmethod
    def _resolve_url(cls, record, url_path):
        if not cls._disable_url_resolution.get():
            pad = record.pad
            plugin = _get_redirect_plugin(pad.env)
            index = plugin.get_index(pad)
            from_url = normalize_url_path(record, "/".join(url_path))
            target = index.get(from_url)
            if target is not None:
                return cls(target, from_url)
        return None

    @classmethod
    def _generator(cls, source):
        if not isinstance(source, Record):
            return  # ignore assets

        plugin = _get_redirect_plugin(source.pad.env)
        for redirect_url in plugin.get_redirect_urls(source):
            yield cls(source, redirect_url)

    class BuildProgram(BuildProgram):
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
            plugin = _get_redirect_plugin(self.build_state.env)
            template = plugin.redirect_template
            values = {"target": source.target}
            artifact.render_template_into(template, this=source, values=values)


_HASH_BYTES = (sys.hash_info.width + 7) // 8


class RedirectMap(_VirtualSourceBase):
    VPATH_PREFIX = "redirect-map"

    @cached_property
    def redirect_map(self):
        plugin = _get_redirect_plugin(self.pad.env)
        return dict(plugin.iter_redirect_map(self.pad))

    def get_checksum(self, path_cache):
        h = hashlib.md5()
        for from_url, to_url in self.redirect_map.items():
            h.update(f"{from_url}\0{to_url}\0".encode())
        return h.hexdigest()

    @classmethod
    def _resolve_url(cls, record, url_path):
        if record.path == "/":
            pad = record.pad
            plugin = _get_redirect_plugin(pad.env)
            map_url = normalize_url_path(record, "/".join(url_path))
            if map_url == plugin.redirect_map_url:
                return RedirectMap(record, map_url)
        return None

    @classmethod
    def _generator(cls, source):
        if source.path == "/":
            pad = source.pad
            plugin = _get_redirect_plugin(pad.env)
            redirect_map_url = plugin.redirect_map_url
            if redirect_map_url is not None:
                yield RedirectMap(source, redirect_map_url)

    class BuildProgram(BuildProgram):
        def produce_artifacts(self):
            source = self.source
            artifact_name = source.url_path
            sources = list(source.record.iter_source_filenames())
            self.declare_artifact(artifact_name, sources=sources)

        def build_artifact(self, artifact):
            quote = nginx_quote_for_map
            with artifact.open("w") as fp:
                for from_url, to_url in self.source.redirect_map.items():
                    print(f"{quote(from_url)} {quote(to_url)};", file=fp)
