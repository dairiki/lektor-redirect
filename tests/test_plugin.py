import io
import os
import re
from operator import attrgetter
from unittest import mock

import pytest
from lektor.db import Attachment

from lektor_redirect import (
    _nginx_escape,
    DEFAULT_TEMPLATE,
    disable_redirect_resolution,
    iter_redirect_urls,
    normalize_url_path,
    Redirect,
    RedirectBuildProgram,
    RedirectIndex,
    RedirectMap,
    RedirectMapBuildProgram,
    RedirectPlugin,
    walk_records,
)


@pytest.fixture
def load_plugin(env):
    # Load our plugin
    env.plugin_controller.instanciate_plugin("redirect", RedirectPlugin)
    env.plugin_controller.emit("setup-env")


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
        Redirect.declare_vpath_resolver(env)
        pad = env.new_pad()
        source = pad.get(source_path)
        assert pad.get(redirect_path) == Redirect(source, url_path)


@pytest.mark.usefixtures("load_plugin")
class TestRedirectMap:
    @pytest.fixture
    def source(self, pad):
        return RedirectMap(pad.root, "/.redirect.map")

    def test_get_redirect_map(self, source):
        assert source.get_redirect_map() == [
            ("/about/info/", "/about/more-detail/"),
            ("/about/projects.html", "/projects/"),
            ("/details/", "/about/more-detail/"),
            ("/images/apple-cake.jpg", "/images/apple-pie.jpg"),
        ]

    def test_get_checksum(self, source, mocker):
        path_cache = mocker.Mock(name="path_cache")
        checksum = source.get_checksum(path_cache)
        assert checksum == "baddf4094f10738328ab2c09c4a44d27"


@pytest.mark.usefixtures("context", "load_plugin")
class TestRedirectBuildProgram:
    @pytest.fixture
    def source(self, pad):
        return Redirect(pad.get("/about"), "/details/")

    @pytest.fixture
    def build_program(self, source, build_state):
        return RedirectBuildProgram(source, build_state)

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
        build_program = RedirectBuildProgram(img_source, build_state)
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


@pytest.mark.usefixtures("load_plugin")
class TestRedirectMapBuildProgram:
    @pytest.fixture
    def source(self, pad):
        return RedirectMap(pad.root, "/.redirect.map")

    @pytest.fixture
    def build_program(self, source, build_state):
        return RedirectMapBuildProgram(source, build_state)

    def test_produce_artifacts(self, build_program, mocker):
        source = build_program.source
        declare_artifact = mocker.patch.object(build_program, "declare_artifact")

        build_program.produce_artifacts()

        sources = list(source.record.iter_source_filenames())
        assert declare_artifact.mock_calls == [
            mock.call("/.redirect.map", sources=sources)
        ]

    @pytest.mark.parametrize(
        "project_url, prefix",
        [
            (None, "/"),
            ("https://example.org/prefix/", "/prefix/"),
        ],
    )
    def test_build_artifact(
        self,
        source,
        build_program,
        mocker,
        project_url,
        prefix,
        open_site_config,
    ):
        if project_url:
            with open_site_config() as inifile:
                inifile["project.url"] = project_url
            builder = build_program.build_state.builder
            builder.pad = builder.env.new_pad()

        buf = io.StringIO()
        mocker.patch.object(buf, "close")
        artifact = mocker.Mock(name="artifact")
        artifact.open.return_value = buf

        build_program.build_artifact(artifact)

        assert buf.getvalue() == (
            f"{prefix}about/info/ {prefix}about/more-detail/;\n"
            f"{prefix}about/projects.html {prefix}projects/;\n"
            f"{prefix}details/ {prefix}about/more-detail/;\n"
            f"{prefix}images/apple-cake.jpg {prefix}images/apple-pie.jpg;\n"
        )


class TestRedirectIndex:
    @pytest.fixture
    def index(self, pad):
        return RedirectIndex(pad)

    def test_mapping(self, index, pad):
        assert dict(index) == {
            "/about/info/": pad.get("/about/more-detail"),
            "/details/": pad.get("/about/more-detail"),
            "/about/projects.html": pad.get("/projects"),
            "/images/apple-cake.jpg": pad.get("/images/apple-pie.jpg"),
        }
        assert len(index) == 4

    def test_iter_redirect_map(self, index):
        redirect_map = list(index.iter_redirect_map())
        expected = [
            ("/about/info/", "/about/more-detail/"),
            ("/details/", "/about/more-detail/"),
            ("/about/projects.html", "/projects/"),
            ("/images/apple-cake.jpg", "/images/apple-pie.jpg"),
        ]
        assert len(redirect_map) == len(expected)
        assert set(redirect_map) == set(expected)

    @pytest.mark.parametrize(
        "source_path, url_path, conflict_path",
        [
            ("/about/more-detail", "/details/", None),
            # Redirect conflicts with existing page
            ("/about/more-detail", "/projects/", "/projects"),
            # Redirect conflicts with another redirect
            ("/about/more-detail", "/about/projects.html", "/projects"),
        ],
    )
    def test_check_for_conflict(self, index, pad, source_path, url_path, conflict_path):
        source = pad.get(source_path)
        if conflict_path is None:
            assert not index.check_for_conflict(url_path, source)
        else:
            assert index.check_for_conflict(url_path, source)


class TestRedirectPlugin:
    @pytest.fixture
    def plugin(self, env):
        return RedirectPlugin(env, "redirect")

    @pytest.fixture
    def source(self, pad, source_path):
        source = pad.get(source_path)
        assert source is not None
        return source

    @pytest.fixture
    def asset(self, pad):
        return pad.get_asset("/static/style.css")

    def test_get_index(self, plugin, open_config_file):
        pad = plugin.env.new_pad()
        index = plugin.get_index(pad)
        assert plugin.get_index(pad) is index
        assert plugin.get_index(plugin.env.new_pad()) is not index

    def test_redirect_from_field(self, plugin):
        assert plugin.redirect_from_field == "redirect_from"

    def test_redirect_from_field_is_configurable(self, plugin, open_config_file):
        with open_config_file() as inifile:
            inifile["redirect.redirect_from_field"] = "old_urls"
        assert plugin.redirect_from_field == "old_urls"

    def test_redirect_template(self, plugin):
        assert plugin.redirect_template == DEFAULT_TEMPLATE

    def test_redirect_template_from_config(self, plugin, open_config_file):
        with open_config_file() as inifile:
            inifile["redirect.template"] = "custom.html"
        assert plugin.redirect_template == "custom.html"

    @pytest.mark.parametrize(
        "map_file, map_url",
        [
            (".redirect.map", "/.redirect.map"),
        ],
    )
    def test_redirect_map_url(self, plugin, map_file, map_url, open_config_file):
        with open_config_file() as inifile:
            inifile["redirect.map_file"] = map_file
        assert plugin.redirect_map_url == map_url

    def test_redirect_map_url_none(self, plugin, open_config_file):
        assert plugin.redirect_map_url is None

    def test_on_setup_env(self, env, plugin):
        plugin.on_setup_env()

        assert (Redirect, RedirectBuildProgram) in env.build_programs
        assert plugin.generate_redirects in env.custom_generators
        assert plugin.generate_redirect_map in env.custom_generators
        assert env.virtual_sources["redirect"] == Redirect._vpath_resolver
        assert env.virtual_sources["redirect-map"] == RedirectMap._vpath_resolver
        assert plugin.resolve_url in env.custom_url_resolvers

    def test_on_setup_env_fails_if_alts_enabled(self, env, plugin, open_site_config):
        with open_site_config() as inifile:
            inifile["alternatives.en.primary"] = "yes"
        with pytest.raises(RuntimeError, match="does not support alts"):
            plugin.on_setup_env()

    @pytest.mark.parametrize(
        "source_path, url_paths",
        [
            ("/projects", ["/about/projects.html"]),
            ("/about/more-detail", ["/about/info/", "/details/"]),
            ("/about", []),
            ("/", []),
        ],
    )
    def test_generate_redirects(self, plugin, source, url_paths):
        redirects = list(plugin.generate_redirects(source))
        assert all(redirect.parent is source for redirect in redirects)
        assert set(map(attrgetter("url_path"), redirects)) == set(url_paths)

    def test_generate_redirects_ignores_redirect_to_self(
        self, plugin, pad, set_redirect_from
    ):
        set_redirect_from(
            "/about/more-detail", ["/about", "/about/", "about-this.html"]
        )
        pad.cache.flush()
        source = pad.get("/about/more-detail")
        redirects = plugin.generate_redirects(source)
        assert list(map(attrgetter("url_path"), redirects)) == [
            "/about/about-this.html"
        ]

    def test_generate_redirects_skips_conflicts(
        self, plugin, pad, set_redirect_from, captured_reports
    ):
        set_redirect_from("/about", ["/about/more-detail"])
        pad.cache.flush()
        source = pad.get("/about")
        redirects = plugin.generate_redirects(source)
        assert list(redirects) == []
        assert captured_reports.message_matches(r"REDIRECT CONFLICT")

    def test_generate_redirects_ignores_assets(self, plugin, asset):
        assert list(plugin.generate_redirects(asset)) == []

    def test_generate_redirect_map(self, plugin, pad, open_config_file):
        with open_config_file() as inifile:
            inifile["redirect.map_file"] = ".redirect.map"
        assert list(plugin.generate_redirect_map(pad.root)) == [
            RedirectMap(pad.root, "/.redirect.map"),
        ]
        assert list(plugin.generate_redirect_map(pad.get("/about"))) == []

    def test_generate_redirect_map_disabled(self, plugin, pad):
        assert list(plugin.generate_redirect_map(pad.root)) == []

    @pytest.mark.parametrize(
        "source_path, url_path, redirect_path",
        [
            ("/about", ["info"], "/about/more-detail@redirect/about/info"),
            ("/", ["details"], "/about/more-detail@redirect/details"),
            ("/", ["about", "projects.html"], "/projects@redirect/about/projects.html"),
        ],
    )
    def test_resolve_url(self, plugin, source, url_path, redirect_path):
        redirect = plugin.resolve_url(source, url_path)
        assert redirect.path == redirect_path

    def test_resolve_url_fails(self, plugin, pad):
        redirect = plugin.resolve_url(pad.root, ["no-such-redir"])
        assert redirect is None

    def test_resolve_url_disabled(self, plugin, pad):
        with disable_redirect_resolution():
            redirect = plugin.resolve_url(pad.root, ["details"])
        assert redirect is None

    def test_resolve_url_redirect_map(self, plugin, pad, open_config_file):
        with open_config_file() as inifile:
            inifile["redirect.map_file"] = ".redirect.map"
        redirect_map = plugin.resolve_url(pad.root, [".redirect.map"])
        assert redirect_map == RedirectMap(pad.root, "/.redirect.map")

    def test_resolve_url_redirect_map_fails(self, plugin, pad, open_config_file):
        with open_config_file() as inifile:
            inifile["redirect.map_file"] = ".redirect.map"
        redirect_map = plugin.resolve_url(pad.root, ["/subdir/.redirect.map"])
        assert redirect_map is None


class Test_iter_redirect_urls:
    @pytest.fixture
    def record(self, pad):
        return pad.get("/about/more-detail")

    def test(self, record):
        assert set(iter_redirect_urls(record)) == {"/about/info/", "/details/"}

    def test_survives_non_subscriptable_records(self):
        assert list(iter_redirect_urls(None)) == []

    def test_explicit_field_name(self, record):
        assert list(iter_redirect_urls(record, "x")) == []


class Test_normalize_url_path:
    @pytest.fixture
    def record(self, pad):
        return pad.get("/about")

    @pytest.mark.parametrize(
        "url_path, normalized",
        [
            ("/foo", "/foo/"),
            ("/foo/", "/foo/"),
            ("///foo//", "/foo/"),
            ("/foo.txt", "/foo.txt"),
            ("/name/../foo.txt", "/foo.txt"),
            ("foo.txt", "/about/foo.txt"),
            ("../foo.txt", "/foo.txt"),
            ("../foo", "/foo/"),
        ],
    )
    def test(self, record, url_path, normalized):
        assert normalize_url_path(record, url_path) == normalized


class Test_walk_records:
    @pytest.fixture
    def apple_pie(self, pad):
        apple_pie = pad.get("/images/apple-pie.jpg")
        assert isinstance(apple_pie, Attachment)
        return apple_pie

    def test_includes_attachments(self, pad, apple_pie):
        assert apple_pie in walk_records(pad)


@pytest.mark.parametrize(
    "str, expected",
    [
        ("", ""),
        ("/foo/bar.html", "/foo/bar.html"),
        ('a"b', "'a\"b'"),
        ("/test run/", '"/test run/"'),
        ("include", r"\include"),
    ],
)
def test_nginx_escape(str, expected):
    assert _nginx_escape(str) == expected
