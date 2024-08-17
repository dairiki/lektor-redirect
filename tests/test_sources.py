import io
import os
import re
from operator import attrgetter
from unittest import mock

import pytest

from lektor_redirect.sources import Redirect, RedirectMap


@pytest.fixture
def source(source_path, pad):
    return pad.get(source_path)


class TestRedirect:
    @pytest.fixture
    def record_path(self):
        return "/about"

    @pytest.fixture
    def url_path(self):
        return "/foo/"

    @pytest.fixture
    def record(self, pad, record_path):
        record = pad.get(record_path)
        assert record is not None
        return record

    @pytest.fixture
    def redirect(self, record, url_path):
        return Redirect(record, url_path)

    @pytest.mark.parametrize(
        "record_path, url_path, redirect_path",
        [
            ("/", "/flag.html", "/@redirect/flag.html"),
            ("/about", "/see/other/", "/about@redirect/see/other"),
        ],
    )
    def test_path(self, redirect, redirect_path):
        assert redirect.path == redirect_path

    def test_target(self, redirect, record):
        assert redirect.target is record

    def test_eq_self(self, redirect):
        assert redirect == redirect
        assert not (redirect != redirect)
        assert hash(redirect) == hash(redirect)

    def test_eq_copy(self, redirect):
        other = Redirect(redirect.parent, redirect.url_path)
        assert redirect == other
        assert not (redirect != other)
        assert hash(redirect) == hash(other)

    def test_ne_copy(self, redirect):
        other = Redirect(redirect.parent, redirect.url_path + "other/")
        assert redirect != other
        assert not (redirect == other)
        assert hash(redirect) != hash(other)

    def test_ne_object(self, redirect):
        other = object()
        assert redirect != other
        assert not (redirect == other)
        assert hash(redirect) != hash(other)

    def test_repr(self, redirect):
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
    def test_vpath_resolver(self, env, source_path, url_path, redirect_path):
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
    def test_generator(self, pad, source, url_paths):
        redirects = list(Redirect._generator(source))
        assert all(redirect.parent is source for redirect in redirects)
        assert set(map(attrgetter("url_path"), redirects)) == set(url_paths)

    @pytest.mark.usefixtures("plugin")
    def test_generator_ignores_redirect_to_self(self, pad, set_redirect_from):
        set_redirect_from(
            "/about/more-detail", ["/about", "/about/", "about-this.html"]
        )
        pad.cache.flush()
        source = pad.get("/about/more-detail")
        redirects = Redirect._generator(source)
        assert list(map(attrgetter("url_path"), redirects)) == [
            "/about/about-this.html"
        ]

    @pytest.mark.usefixtures("plugin")
    def test_generator_skips_conflicts(self, pad, set_redirect_from, captured_reports):
        set_redirect_from("/about", ["/about/more-detail"])
        pad.cache.flush()
        source = pad.get("/about")
        redirects = Redirect._generator(source)
        assert list(redirects) == []
        assert captured_reports.message_matches(r"Invalid redirect\b.*\bconflicts with")

    @pytest.mark.usefixtures("plugin")
    def test_generator_ignores_assets(self, pad):
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
    def test_resolve_url(self, source, url_path, redirect_path):
        redirect = Redirect._resolve_url(source, url_path)
        assert redirect.path == redirect_path

    @pytest.mark.usefixtures("plugin")
    def test_resolve_url_fails(self, pad):
        redirect = Redirect._resolve_url(pad.root, ["no-such-redir"])
        assert redirect is None

    @pytest.mark.usefixtures("plugin")
    def test_resolve_url_disabled(self, pad):
        with Redirect.disable_url_resolution():
            redirect = Redirect._resolve_url(pad.root, ["details"])
        assert redirect is None


@pytest.mark.usefixtures("plugin")
class TestRedirectMap:
    @pytest.fixture
    def source(self, pad):
        return RedirectMap(pad.root, "/.redirect.map")

    def test_redirect_map(self, source):
        assert source.redirect_map == {
            "/about/info/": "/about/more-detail/",
            "/about/projects.html": "/projects/",
            "/details/": "/about/more-detail/",
            "/images/apple-cake.jpg": "/images/apple-pie.jpg",
        }

    def test_get_checksum(self, source, mocker):
        path_cache = mocker.Mock(name="path_cache")
        checksum = source.get_checksum(path_cache)
        assert checksum == "baddf4094f10738328ab2c09c4a44d27"

    def test_generator(self, pad, open_config_file):
        with open_config_file() as inifile:
            inifile["redirect.map_file"] = ".redirect.map"
        assert list(RedirectMap._generator(pad.root)) == [
            RedirectMap(pad.root, "/.redirect.map"),
        ]
        assert list(RedirectMap._generator(pad.get("/about"))) == []

    @pytest.mark.usefixtures("redirect_map_disabled")
    def test_generator_disabled(self, pad):
        assert list(RedirectMap._generator(pad.root)) == []

    @pytest.mark.usefixtures("plugin")
    def test_resolve_url(self, pad, open_config_file):
        with open_config_file() as inifile:
            inifile["redirect.map_file"] = ".redirect.map"
        redirect_map = RedirectMap._resolve_url(pad.root, [".redirect.map"])
        assert redirect_map == RedirectMap(pad.root, "/.redirect.map")

    @pytest.mark.usefixtures("plugin")
    def test_resolve_url_fails(self, pad, open_config_file):
        with open_config_file() as inifile:
            inifile["redirect.map_file"] = ".redirect.map"
        redirect_map = RedirectMap._resolve_url(pad.root, ["/subdir/.redirect.map"])
        assert redirect_map is None


@pytest.mark.usefixtures("context", "plugin")
class TestRedirectBuildProgram:
    @pytest.fixture
    def source(self, pad):
        return Redirect(pad.get("/about"), "/details/")

    @pytest.fixture
    def build_program(self, source, build_state):
        return Redirect.BuildProgram(source, build_state)

    @pytest.fixture
    def img_source(self, pad):
        return Redirect(pad.get("/images/apple-pie.jpg"), "/images/apple-cake.jpg")

    @pytest.fixture
    def declare_artifact(self, build_program, mocker):
        return mocker.patch.object(build_program, "declare_artifact")

    def test_produce_artifacts(self, build_program, source, declare_artifact):
        build_program.produce_artifacts()
        sources = list(source.parent.iter_source_filenames())
        assert declare_artifact.mock_calls == [
            mock.call("/details/index.html", sources=sources)
        ]

    def test_produce_non_html_artifacts(self, img_source, build_state, mocker):
        build_program = Redirect.BuildProgram(img_source, build_state)
        declare_artifact = mocker.patch.object(build_program, "declare_artifact")

        build_program.produce_artifacts()
        sources = list(img_source.parent.iter_source_filenames())
        assert declare_artifact.mock_calls == [
            mock.call("/images/apple-cake.jpg/index.html", sources=sources),
        ]

    def test_build_artifact(self, source, build_program, mocker):
        artifact = mocker.Mock(name="artifact")
        build_program.build_artifact(artifact)
        values = {"target": source.record}
        assert artifact.mock_calls == [
            mock.call.render_template_into("redirect.html", this=source, values=values),
        ]

    def test_build_artifact_records_dependency(
        self, source, build_program, env, context, mocker
    ):
        config_filename = os.path.join(env.root_path, "configs/redirect.ini")
        artifact = mocker.Mock(name="artifact")
        build_program.build_artifact(artifact)
        assert config_filename in context.referenced_dependencies


@pytest.mark.usefixtures("plugin")
class TestRedirectMapBuildProgram:
    @pytest.fixture
    def source(self, pad):
        return RedirectMap(pad.root, "/.redirect.map")

    @pytest.fixture
    def build_program(self, source, build_state):
        return RedirectMap.BuildProgram(source, build_state)

    def test_produce_artifacts(self, build_program, mocker):
        source = build_program.source
        declare_artifact = mocker.patch.object(build_program, "declare_artifact")

        build_program.produce_artifacts()

        sources = list(source.record.iter_source_filenames())
        assert declare_artifact.mock_calls == [
            mock.call("/.redirect.map", sources=sources)
        ]

    def test_build_artifact(self, source, build_program, mocker):
        buf = io.StringIO()
        mocker.patch.object(buf, "close")
        artifact = mocker.Mock(name="artifact")
        artifact.open.return_value = buf

        build_program.build_artifact(artifact)

        assert buf.getvalue() == (
            "/about/info/ /about/more-detail/;\n"
            "/about/projects.html /projects/;\n"
            "/details/ /about/more-detail/;\n"
            "/images/apple-cake.jpg /images/apple-pie.jpg;\n"
        )
