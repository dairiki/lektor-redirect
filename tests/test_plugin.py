from __future__ import annotations

from unittest import mock

import pytest
from lektor.db import Pad
from lektor.environment import Environment

from lektor_redirect.exceptions import (
    AmbiguousRedirectException,
    RedirectShadowsExistingRecordException,
    RedirectToSelfException,
)
from lektor_redirect.plugin import RedirectIndex, RedirectPlugin
from lektor_redirect.sources import Redirect, RedirectMap

from .conftest import (
    OpenConfigFileFixture,
    OpenSiteConfigFixture,
    ReporterCaptureFixture,
)


@pytest.mark.usefixtures("plugin")
class TestRedirectPlugin:
    def test_get_index(
        self, plugin: RedirectPlugin, open_config_file: OpenConfigFileFixture
    ) -> None:
        pad = plugin.env.new_pad()
        index = plugin.get_index(pad)
        assert plugin.get_index(pad) is index
        assert plugin.get_index(plugin.env.new_pad()) is not index

    def test_redirect_from_field(self, plugin: RedirectPlugin) -> None:
        assert plugin.redirect_from_field == "redirect_from"

    def test_redirect_from_field_is_configurable(
        self, plugin: RedirectPlugin, open_config_file: OpenConfigFileFixture
    ) -> None:
        with open_config_file() as inifile:
            inifile["redirect.redirect_from_field"] = "old_urls"
        assert plugin.redirect_from_field == "old_urls"

    def test_redirect_template(
        self, plugin: RedirectPlugin, open_config_file: OpenConfigFileFixture
    ) -> None:
        with open_config_file() as inifile:
            inifile["redirect.template"] = "custom.html"
        assert plugin.redirect_template == "custom.html"

    def test_redirect_template_none(
        self, plugin: RedirectPlugin, open_config_file: OpenConfigFileFixture
    ) -> None:
        with open_config_file() as inifile:
            inifile.pop("redirect.template", None)
        assert plugin.redirect_template is None

    @pytest.mark.parametrize(
        "map_file, map_url",
        [
            (".redirect.map", "/.redirect.map"),
        ],
    )
    def test_redirect_map_url(
        self,
        plugin: RedirectPlugin,
        map_file: str,
        map_url: str,
        open_config_file: OpenConfigFileFixture,
    ) -> None:
        with open_config_file() as inifile:
            inifile["redirect.map_file"] = map_file
        assert plugin.redirect_map_url == map_url

    @pytest.mark.usefixtures("redirect_map_disabled")
    def test_redirect_map_url_none(self, plugin: RedirectPlugin) -> None:
        assert plugin.redirect_map_url is None

    def test_get_redirect_urls(self, plugin: RedirectPlugin, pad: Pad) -> None:
        record = pad.get("/about/more-detail")
        assert plugin.get_redirect_urls(record) == {"/about/info/", "/details/"}

    def test_get_redirect_urls_survives_non_subscriptable_records(
        self, plugin: RedirectPlugin
    ) -> None:
        assert len(plugin.get_redirect_urls(None)) == 0

    @pytest.mark.parametrize(
        "project_url, prefix",
        [
            (None, "/"),
            ("https://example.org/prefix/", "/prefix/"),
        ],
    )
    def test_iter_redirect_map(
        self, plugin: RedirectPlugin, pad: Pad, prefix: str
    ) -> None:
        assert list(plugin.iter_redirect_map(pad)) == [
            (f"{prefix}about/info/", f"{prefix}about/more-detail/"),
            (f"{prefix}about/projects.html", f"{prefix}projects/"),
            (f"{prefix}details/", f"{prefix}about/more-detail/"),
            (f"{prefix}images/apple-cake.jpg", f"{prefix}images/apple-pie.jpg"),
        ]

    def test_on_setup_env(self, env: Environment, plugin: RedirectPlugin) -> None:
        assert (Redirect, Redirect.BuildProgram) in env.build_programs
        assert (RedirectMap, RedirectMap.BuildProgram) in env.build_programs
        assert Redirect._generator in env.custom_generators
        assert RedirectMap._generator in env.custom_generators
        assert env.virtual_sources["redirect"] == Redirect._vpath_resolver
        assert env.virtual_sources["redirect-map"] == RedirectMap._vpath_resolver
        assert Redirect._resolve_url_path in env.custom_url_resolvers
        assert RedirectMap._resolve_url_path in env.custom_url_resolvers

    def test_on_setup_env_fails_if_alts_enabled(
        self, plugin: RedirectPlugin, open_site_config: OpenSiteConfigFixture
    ) -> None:
        with open_site_config() as inifile:
            inifile["alternatives.en.primary"] = "yes"
        with pytest.raises(RuntimeError, match="does not support alts"):
            plugin.on_setup_env()

    def test_on_before_build_all_fails_if_alts_enabled(
        self, plugin: RedirectPlugin, open_site_config: OpenSiteConfigFixture
    ) -> None:
        with open_site_config() as inifile:
            inifile["alternatives.en.primary"] = "yes"
        builder = mock.Mock(name="builder")
        with pytest.raises(RuntimeError, match="does not support alts"):
            plugin.on_before_build_all(builder)


@pytest.mark.usefixtures("plugin")
class TestRedirectIndex:
    @pytest.fixture
    def index(self, pad: Pad) -> RedirectIndex:
        return RedirectIndex(pad)

    def test_mapping(self, index: RedirectIndex, pad: Pad) -> None:
        assert dict(index) == {
            "/about/info/": pad.get("/about/more-detail"),
            "/details/": pad.get("/about/more-detail"),
            "/about/projects.html": pad.get("/projects"),
            "/images/apple-cake.jpg": pad.get("/images/apple-pie.jpg"),
        }
        assert len(index) == 4

    @pytest.mark.parametrize(
        "source_path, url_path, exc_type",
        [
            ("/about/more-detail", "/details/", None),
            # Redirect conflicts to self
            ("/projects", "/projects/", RedirectToSelfException),
            # Redirect conflicts with existing page
            (
                "/about/more-detail",
                "/projects/",
                RedirectShadowsExistingRecordException,
            ),
            # Redirect conflicts with another redirect
            ("/about/more-detail", "/about/projects.html", AmbiguousRedirectException),
        ],
    )
    def test_raise_on_conflict(
        self,
        index: RedirectIndex,
        pad: Pad,
        source_path: str,
        url_path: str,
        exc_type: type[Exception],
    ) -> None:
        source = pad.get(source_path)
        if exc_type is None:
            index.raise_on_conflict(url_path, source)
        else:
            with pytest.raises(exc_type):
                index.raise_on_conflict(url_path, source)

    def test_is_conflict(
        self, index: RedirectIndex, pad: Pad, captured_reports: ReporterCaptureFixture
    ) -> None:
        more_detail = pad.get("/about/more-detail")
        assert index.is_conflict("/about/projects.html", more_detail)
        assert captured_reports.message_matches(
            r"Invalid redirect\b.*\bconflicts with redirect"
        )
