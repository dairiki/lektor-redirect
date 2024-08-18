from __future__ import annotations

import hashlib
import posixpath
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from functools import cached_property
from typing import ClassVar, Final, Iterator, Mapping, Sequence, TYPE_CHECKING

from lektor.build_programs import BuildProgram as LektorBuildProgram
from lektor.builder import Artifact, PathCache
from lektor.db import Record
from lektor.environment import Environment
from lektor.pluginsystem import get_plugin
from lektor.sourceobj import VirtualSourceObject

from .util import nginx_quote_for_map, normalize_url_path

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

if TYPE_CHECKING:
    from lektor_redirect.plugin import RedirectPlugin  # circ dep


HTML_EXTS: Final = {".html", ".htm"}


def _get_redirect_plugin(env: Environment) -> RedirectPlugin:
    from .plugin import RedirectPlugin  # FIXME: circ dep

    redirect_plugin = get_plugin(RedirectPlugin, env)
    assert isinstance(redirect_plugin, RedirectPlugin)
    return redirect_plugin


class _VirtualSourceBase(VirtualSourceObject):  # type: ignore[misc]
    url_path: str = ""  # override inherited property

    def __init__(self, record: Record, url_path: str):
        super().__init__(record)
        self.url_path = url_path

    @property
    def path(self) -> str:
        return f"{self.record.path}" f"@{self.VPATH_PREFIX}{self.url_path.rstrip('/')}"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _VirtualSourceBase):
            return self.path == other.path
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.path)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.record!r}, {self.url_path!r})"

    @classmethod
    def _setup_env(cls, env: Environment) -> None:
        env.add_build_program(cls, cls.BuildProgram)
        env.generator(cls._generator)
        env.virtualpathresolver(cls.VPATH_PREFIX)(cls._vpath_resolver)
        env.urlresolver(cls._resolve_url_path)

    @classmethod
    def _vpath_resolver(cls, record: Record, pieces: Sequence[str]) -> Self:
        url_path = "/" + "/".join(pieces)
        if "." not in pieces[-1]:
            url_path += "/"
        return cls(record, url_path)

    @classmethod
    def _generator(cls, source: Record) -> Iterator[Self]:
        raise NotImplementedError

    @classmethod
    def _resolve_url_path(cls, record: Record, url_path: Sequence[str]) -> Self | None:
        raise NotImplementedError


class Redirect(_VirtualSourceBase):
    VPATH_PREFIX: Final = "redirect"

    @property
    def target(self) -> Record:
        """The target record of the redirect."""
        return self.record

    _disable_url_resolution: ClassVar = ContextVar(
        f"{__qualname__}._disable_url_resolution", default=False
    )

    @classmethod
    @contextmanager
    def disable_url_resolution(cls) -> Iterator[None]:
        token = cls._disable_url_resolution.set(True)
        try:
            yield
        finally:
            cls._disable_url_resolution.reset(token)

    @classmethod
    def _resolve_url_path(cls, record: Record, url_path: Sequence[str]) -> Self | None:
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
    def _generator(cls, source: Record) -> Iterator[Self]:
        if not isinstance(source, Record):
            return  # ignore assets

        plugin = _get_redirect_plugin(source.pad.env)
        template = plugin.redirect_template
        if template:
            for redirect_url in plugin.get_redirect_urls(source):
                yield cls(source, redirect_url)

    class BuildProgram(LektorBuildProgram):  # type: ignore[misc]
        def produce_artifacts(self) -> None:
            source = self.source

            artifact_name = source.url_path
            if artifact_name.endswith("/"):
                artifact_name += "index.html"
            elif posixpath.splitext(artifact_name)[1].lower() not in HTML_EXTS:
                artifact_name += "/index.html"

            sources = list(source.record.iter_source_filenames())

            self.declare_artifact(artifact_name, sources=sources)

        def build_artifact(self, artifact: Artifact) -> None:
            plugin = _get_redirect_plugin(self.build_state.env)
            template = plugin.redirect_template
            if template:
                artifact.render_template_into(template, this=self.source)


_HASH_BYTES: Final = (sys.hash_info.width + 7) // 8


class RedirectMap(_VirtualSourceBase):
    VPATH_PREFIX: Final = "redirect-map"

    @cached_property
    def redirect_map(self) -> Mapping[str, str]:
        plugin = _get_redirect_plugin(self.pad.env)
        return dict(plugin.iter_redirect_map(self.pad))

    def get_checksum(self, path_cache: PathCache) -> str:
        h = hashlib.md5()
        for from_url, to_url in self.redirect_map.items():
            h.update(f"{from_url}\0{to_url}\0".encode())
        return h.hexdigest()

    @classmethod
    def _resolve_url_path(cls, record: Record, url_path: Sequence[str]) -> Self | None:
        if record.path == "/":
            pad = record.pad
            plugin = _get_redirect_plugin(pad.env)
            map_url = normalize_url_path(record, "/".join(url_path))
            if map_url == plugin.redirect_map_url:
                return RedirectMap(record, map_url)
        return None

    @classmethod
    def _generator(cls, source: Record) -> Iterator[Self]:
        if source.path == "/":
            pad = source.pad
            plugin = _get_redirect_plugin(pad.env)
            redirect_map_url = plugin.redirect_map_url
            if redirect_map_url is not None:
                yield RedirectMap(source, redirect_map_url)

    class BuildProgram(LektorBuildProgram):  # type: ignore[misc]
        def produce_artifacts(self) -> None:
            source = self.source
            artifact_name = source.url_path
            sources = list(source.record.iter_source_filenames())
            self.declare_artifact(artifact_name, sources=sources)

        def build_artifact(self, artifact: Artifact) -> None:
            quote = nginx_quote_for_map
            with artifact.open("w") as fp:
                for from_url, to_url in self.source.redirect_map.items():
                    print(f"{quote(from_url)} {quote(to_url)};", file=fp)
