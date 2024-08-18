from __future__ import annotations

import io
import os
import re
from contextlib import contextmanager
from operator import attrgetter
from typing import Iterable, Iterator
from unittest import mock

import pytest
from lektor.builder import BuildState
from lektor.context import Context
from lektor.db import Pad, Record
from lektor.environment import Environment

from lektor_redirect.sources import Redirect, RedirectMap

from .conftest import (
    OpenConfigFileFixture,
    ReporterCaptureFixture,
    SetRedirectFromFixture,
)


@pytest.fixture
def source(source_path: str, pad: Pad) -> Record:
    record = pad.get(source_path)
    assert isinstance(record, Record)
    return record


class TestRedirect:
    @pytest.fixture
    def record_path(self) -> str:
        return "/about"

    @pytest.fixture
    def url_path(self) -> str:
        return "/foo/"

    @pytest.fixture
    def record(self, pad: Pad, record_path: str) -> Record:
        record = pad.get(record_path)
        assert isinstance(record, Record)
        return record

    @pytest.fixture
    def redirect(self, record: Record, url_path: str) -> Redirect:
        return Redirect(record, url_path)

    @pytest.mark.parametrize(
        "record_path, url_path, redirect_path",
        [
            ("/", "/flag.html", "/@redirect/flag.html"),
            ("/about", "/see/other/", "/about@redirect/see/other"),
        ],
    )
    def test_path(self, redirect: Redirect, redirect_path: str) -> None:
        assert redirect.path == redirect_path

    def test_target(self, redirect: Redirect, record: Record) -> None:
        assert redirect.target is record

    def test_eq_self(self, redirect: Record) -> None:
        assert redirect == redirect
        assert not (redirect != redirect)
        assert hash(redirect) == hash(redirect)

    def test_eq_copy(self, redirect: Record) -> None:
        other = Redirect(redirect.parent, redirect.url_path)
        assert redirect == other
        assert not (redirect != other)
        assert hash(redirect) == hash(other)

    def test_ne_copy(self, redirect: Record) -> None:
        other = Redirect(redirect.parent, redirect.url_path + "other/")
        assert redirect != other
        assert not (redirect == other)
        assert hash(redirect) != hash(other)

    def test_ne_object(self, redirect: Record) -> None:
        other = object()
        assert redirect != other
        assert not (redirect == other)
        assert hash(redirect) != hash(other)

    def test_repr(self, redirect: Redirect) -> None:
        assert re.fullmatch(
            r'Redirect\(<Page .*path=(["\'])/about\1.*>, (["\'])/foo/\2\)',
            repr(redirect),
        )

    @pytest.mark.parametrize(
        "source_path, url_path, redirect_path",
        [
            ("/about", "/foo/bar.txt", "/about@redirect/foo/bar.txt"),
            ("/", "/foo", "/@redirect/foo"),
            ("/", "/foo", "/@redirect/foo/"),
        ],
    )
    def test_vpath_resolver(
        self, env: Environment, source_path: str, url_path: str, redirect_path: str
    ) -> None:
        Redirect._setup_env(env)
        pad = env.new_pad()
        source = pad.get(source_path)
        assert pad.get(redirect_path) == Redirect(source, url_path)

    @pytest.mark.parametrize(
        "source_path, url_paths",
        [
            ("/projects", ["/about/projects.html"]),
            ("/about/more-detail", ["/about/info/", "/details/"]),
            ("/about", []),
            ("/", []),
        ],
    )
    @pytest.mark.usefixtures("plugin")
    def test_generator(
        self, pad: Pad, source: Record, url_paths: Iterable[str]
    ) -> None:
        redirects = list(Redirect._generator(source))
        assert all(redirect.parent is source for redirect in redirects)
        assert set(map(attrgetter("url_path"), redirects)) == set(url_paths)

    @pytest.mark.usefixtures("plugin")
    def test_generator_disabled_if_no_template(
        self, pad: Pad, open_config_file: OpenConfigFileFixture
    ) -> None:
        with open_config_file() as inifile:
            inifile.pop("redirect.template", None)

        source = pad.get("/projects")
        redirects = list(Redirect._generator(source))
        assert len(redirects) == 0

    @pytest.mark.usefixtures("plugin")
    def test_generator_ignores_redirect_to_self(
        self,
        pad: Pad,
        set_redirect_from: SetRedirectFromFixture,
        captured_reports: ReporterCaptureFixture,
    ) -> None:
        set_redirect_from("/about", ["/about", "/about/", "about-this.html"])
        pad.cache.flush()
        source = pad.get("/about")
        redirects = Redirect._generator(source)
        assert list(map(attrgetter("url_path"), redirects)) == ["/about-this.html"]
        assert len(captured_reports.get_generic_messages()) == 0

    @pytest.mark.parametrize("verbosity", [0, 1])
    @pytest.mark.usefixtures("plugin")
    def test_generator_ignores_redirect_to_self_issues_warning(
        self,
        pad: Pad,
        set_redirect_from: SetRedirectFromFixture,
        captured_reports: ReporterCaptureFixture,
        verbosity: int,
    ) -> None:
        captured_reports.verbosity = verbosity
        set_redirect_from("/about", ["/about", "/about/"])
        pad.cache.flush()
        source = pad.get("/about")
        redirects = Redirect._generator(source)
        assert list(redirects) == []
        messages = captured_reports.get_generic_messages()
        if verbosity >= 1:
            assert len(messages) == 1
            assert re.match(r"Ignoring redirect:.*\bredirect to self", messages[0])
        else:
            assert len(messages) == 0

    @pytest.mark.usefixtures("plugin")
    def test_generator_skips_conflicts(
        self,
        pad: Pad,
        set_redirect_from: SetRedirectFromFixture,
        captured_reports: ReporterCaptureFixture,
    ) -> None:
        set_redirect_from("/about", ["/about/more-detail"])
        pad.cache.flush()
        source = pad.get("/about")
        redirects = Redirect._generator(source)
        assert list(redirects) == []
        assert captured_reports.message_matches(r"Invalid redirect\b.*\bconflicts with")

    @pytest.mark.usefixtures("plugin")
    def test_generator_ignores_assets(self, pad: Pad) -> None:
        asset = pad.get_asset("/static/style.css")
        assert list(Redirect._generator(asset)) == []

    @pytest.mark.parametrize(
        "source_path, url_path, redirect_path",
        [
            ("/about", ["info"], "/about/more-detail@redirect/about/info"),
            ("/", ["details"], "/about/more-detail@redirect/details"),
            ("/", ["about", "projects.html"], "/projects@redirect/about/projects.html"),
        ],
    )
    @pytest.mark.usefixtures("plugin")
    def test_resolve_url_path(
        self, source: Record, url_path: str, redirect_path: str
    ) -> None:
        redirect = Redirect._resolve_url_path(source, url_path)
        assert redirect is not None
        assert redirect.path == redirect_path

    @pytest.mark.usefixtures("plugin")
    def test_resolve_url_path_fails(self, pad: Pad) -> None:
        redirect = Redirect._resolve_url_path(pad.root, ["no-such-redir"])
        assert redirect is None

    @pytest.mark.usefixtures("plugin")
    def test_resolve_url_path_disabled(self, pad: Pad) -> None:
        with Redirect.disable_url_resolution():
            redirect = Redirect._resolve_url_path(pad.root, ["details"])
        assert redirect is None


@pytest.mark.usefixtures("plugin")
class TestRedirectMap:
    @pytest.fixture
    def source(self, pad: Pad) -> RedirectMap:
        return RedirectMap(pad.root, "/.redirect.map")

    def test_redirect_map(self, source: RedirectMap) -> None:
        assert source.redirect_map == {
            "/about/info/": "/about/more-detail/",
            "/about/projects.html": "/projects/",
            "/details/": "/about/more-detail/",
            "/images/apple-cake.jpg": "/images/apple-pie.jpg",
        }

    def test_get_checksum(self, source: RedirectMap) -> None:
        path_cache = mock.Mock(name="path_cache")
        checksum = source.get_checksum(path_cache)
        assert checksum == "baddf4094f10738328ab2c09c4a44d27"

    def test_generator(self, pad: Pad, open_config_file: OpenConfigFileFixture) -> None:
        with open_config_file() as inifile:
            inifile["redirect.map_file"] = ".redirect.map"
        assert list(RedirectMap._generator(pad.root)) == [
            RedirectMap(pad.root, "/.redirect.map"),
        ]
        assert list(RedirectMap._generator(pad.get("/about"))) == []

    @pytest.mark.usefixtures("redirect_map_disabled")
    def test_generator_disabled(self, pad: Pad) -> None:
        assert list(RedirectMap._generator(pad.root)) == []

    @pytest.mark.usefixtures("plugin")
    def test_resolve_url_path(
        self, pad: Pad, open_config_file: OpenConfigFileFixture
    ) -> None:
        with open_config_file() as inifile:
            inifile["redirect.map_file"] = ".redirect.map"
        redirect_map = RedirectMap._resolve_url_path(pad.root, [".redirect.map"])
        assert redirect_map == RedirectMap(pad.root, "/.redirect.map")

    @pytest.mark.usefixtures("plugin")
    def test_resolve_url_path_fails(
        self, pad: Pad, open_config_file: OpenConfigFileFixture
    ) -> None:
        with open_config_file() as inifile:
            inifile["redirect.map_file"] = ".redirect.map"
        redirect_map = RedirectMap._resolve_url_path(
            pad.root, ["/subdir/.redirect.map"]
        )
        assert redirect_map is None


@pytest.mark.usefixtures("context", "plugin")
class TestRedirectBuildProgram:
    @pytest.fixture
    def source(self, pad: Pad) -> Redirect:
        return Redirect(pad.get("/about"), "/details/")

    @pytest.fixture
    def build_program(
        self, source: Redirect, build_state: BuildState
    ) -> Redirect.BuildProgram:
        return Redirect.BuildProgram(source, build_state)

    @pytest.fixture
    def img_source(self, pad: Pad) -> Redirect:
        return Redirect(pad.get("/images/apple-pie.jpg"), "/images/apple-cake.jpg")

    @pytest.fixture
    def declare_artifact(
        self, build_program: Redirect.BuildProgram
    ) -> Iterator[mock.Mock]:
        with mock.patch.object(build_program, "declare_artifact") as patched:
            yield patched

    def test_produce_artifacts(
        self,
        build_program: Redirect.BuildProgram,
        source: Redirect,
        declare_artifact: mock.Mock,
    ) -> None:
        build_program.produce_artifacts()
        sources = list(source.parent.iter_source_filenames())
        assert declare_artifact.mock_calls == [
            mock.call("/details/index.html", sources=sources)
        ]

    def test_produce_non_html_artifacts(
        self, img_source: Record, build_state: BuildState
    ) -> None:
        build_program = Redirect.BuildProgram(img_source, build_state)
        with mock.patch.object(build_program, "declare_artifact") as declare_artifact:
            build_program.produce_artifacts()
            sources = list(img_source.parent.iter_source_filenames())
        assert declare_artifact.mock_calls == [
            mock.call("/images/apple-cake.jpg/index.html", sources=sources),
        ]

    def test_build_artifact(
        self, source: Record, build_program: Redirect.BuildProgram
    ) -> None:
        artifact = mock.Mock(name="artifact")
        build_program.build_artifact(artifact)
        assert artifact.mock_calls == [
            mock.call.render_template_into("redirect.html", this=source)
        ]

    def test_build_artifact_records_dependency(
        self,
        source: Record,
        build_program: Redirect.BuildProgram,
        env: Environment,
        context: Context,
    ) -> None:
        config_filename = os.path.join(env.root_path, "configs/redirect.ini")
        artifact = mock.Mock(name="artifact")
        build_program.build_artifact(artifact)
        assert config_filename in context.referenced_dependencies


@pytest.mark.usefixtures("plugin")
class TestRedirectMapBuildProgram:
    @pytest.fixture
    def source(self, pad: Pad) -> RedirectMap:
        return RedirectMap(pad.root, "/.redirect.map")

    @pytest.fixture
    def build_program(
        self, source: RedirectMap, build_state: BuildState
    ) -> RedirectMap.BuildProgram:
        return RedirectMap.BuildProgram(source, build_state)

    def test_produce_artifacts(self, build_program: RedirectMap.BuildProgram) -> None:
        source = build_program.source
        sources = list(source.record.iter_source_filenames())

        with mock.patch.object(build_program, "declare_artifact") as declare_artifact:
            build_program.produce_artifacts()

        assert declare_artifact.mock_calls == [
            mock.call("/.redirect.map", sources=sources)
        ]

    def test_build_artifact(
        self, source: RedirectMap, build_program: RedirectMap.BuildProgram
    ) -> None:
        buf = io.StringIO()

        @contextmanager
        def artifact_open(mode: str) -> Iterator[io.StringIO]:
            yield buf

        artifact = mock.Mock(name="artifact", open=artifact_open)

        build_program.build_artifact(artifact)

        assert buf.getvalue() == (
            "/about/info/ /about/more-detail/;\n"
            "/about/projects.html /projects/;\n"
            "/details/ /about/more-detail/;\n"
            "/images/apple-cake.jpg /images/apple-pie.jpg;\n"
        )
