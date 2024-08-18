from __future__ import annotations

import os
import re
import shutil
from contextlib import contextmanager, ExitStack
from pathlib import Path
from typing import (
    Callable,
    ContextManager,
    Iterable,
    Iterator,
    MutableMapping,
    TYPE_CHECKING,
)

import pytest
from inifile import IniFile
from lektor import metaformat
from lektor.builder import Builder, BuildState
from lektor.context import Context
from lektor.db import Pad
from lektor.environment import Environment
from lektor.pluginsystem import get_plugin
from lektor.project import Project
from lektor.reporter import BufferReporter

from lektor_redirect import RedirectPlugin

if TYPE_CHECKING:
    from _typeshed import StrPath


@pytest.fixture(scope="session")
def site_dir_src() -> str:
    return os.path.join(os.path.dirname(__file__), "test-site")


@pytest.fixture
def tmp_site_dir(site_dir_src: str, tmp_path: Path) -> Path:
    site_dir = tmp_path / "site"
    shutil.copytree(site_dir_src, site_dir)
    return site_dir


@pytest.fixture
def project_url() -> str | None:
    return None


@pytest.fixture
def site_dir(
    request: pytest.FixtureRequest, site_dir_src: str, project_url: str | None
) -> StrPath:
    if project_url is not None:
        with request.getfixturevalue("open_site_config")() as inifile:
            inifile["project.url"] = project_url

    site_dir: StrPath
    if "tmp_site_dir" in request.fixturenames:
        site_dir = request.getfixturevalue("tmp_site_dir")
    else:
        site_dir = site_dir_src
    return site_dir


@pytest.fixture
def env(site_dir: Path) -> Environment:
    return Project.from_path(site_dir).make_env(load_plugins=False)


@pytest.fixture
def plugin(env: Environment) -> RedirectPlugin:
    # Load our plugin
    env.plugin_controller.instanciate_plugin("redirect", RedirectPlugin)
    env.plugin_controller.emit("setup-env")
    plugin = get_plugin(RedirectPlugin, env)
    assert isinstance(plugin, RedirectPlugin)
    return plugin


@pytest.fixture
def pad(env: Environment) -> Pad:
    return env.new_pad()


@pytest.fixture
def context(pad: Pad) -> Context:
    with Context(pad=pad) as ctx:
        yield ctx


@pytest.fixture
def builder(pad: Pad, tmp_path: Path) -> Builder:
    return Builder(pad, tmp_path / "output")


@pytest.fixture
def build_state(builder: Builder) -> BuildState:
    with ExitStack() as stack:
        build_state = builder.new_build_state()
        # BuildState does not always support the ContextManager interface
        # (e.g. lektor==3.4.0b12)
        if hasattr(build_state, "__exit__"):
            build_state = stack.enter_context(build_state)
        yield build_state


OpenContentsLrFixture = Callable[[str], ContextManager[MutableMapping[str, str]]]


@pytest.fixture
def open_contents_lr(tmp_site_dir: Path) -> OpenContentsLrFixture:
    @contextmanager
    def open_contents_lr(path: str) -> Iterator[MutableMapping[str, str]]:
        path = path.lstrip("/")
        filename = tmp_site_dir / "content" / path / "contents.lr"
        with open(filename, "rb") as f:
            data = {
                key: "".join(lines)
                for key, lines in metaformat.tokenize(f, encoding="utf-8")
            }
        yield data
        with open(filename, "wb") as f:
            f.writelines(metaformat.serialize(data.items(), encoding="utf-8"))

    return open_contents_lr


OpenConfigFileFixture = Callable[[], ContextManager[IniFile]]


@pytest.fixture
def open_config_file(tmp_site_dir: Path) -> OpenConfigFileFixture:
    @contextmanager
    def open_config_file() -> Iterator[IniFile]:
        filename = tmp_site_dir / "configs/redirect.ini"
        filename.parent.mkdir(exist_ok=True)
        inifile = IniFile(filename)
        yield inifile
        inifile.save()

    return open_config_file


OpenSiteConfigFixture = Callable[[], ContextManager[IniFile]]


@pytest.fixture
def open_site_config(tmp_site_dir: Path) -> OpenSiteConfigFixture:
    @contextmanager
    def open_site_config() -> Iterator[IniFile]:
        filename = tmp_site_dir / "Test Site.lektorproject"
        inifile = IniFile(filename)
        yield inifile
        inifile.save()

    return open_site_config


@pytest.fixture
def redirect_map_disabled(open_config_file: OpenConfigFileFixture) -> None:
    with open_config_file() as inifile:
        inifile.pop("redirect.map_file", None)


SetRedirectFromFixture = Callable[[str, Iterable[str]], None]


@pytest.fixture
def set_redirect_from(
    open_contents_lr: OpenContentsLrFixture,
) -> SetRedirectFromFixture:
    def set_redirect_from(path: str, url_paths: Iterable[str]) -> None:
        with open_contents_lr(path) as data:
            data["redirect_from"] = "\n".join(url_paths)

    return set_redirect_from


@pytest.fixture
def captured_reports(env: Environment) -> Iterator[ReporterCaptureFixture]:
    with ReporterCaptureFixture(env) as reporter:
        yield reporter


class ReporterCaptureFixture(BufferReporter):  # type: ignore[misc]
    def get_generic_messages(self) -> list[str]:
        return [
            data.get("message") for event, data in self.buffer if event == "generic"
        ]

    def message_matches(self, match: str | re.Pattern[str]) -> bool:
        return any(re.match(match, message) for message in self.get_generic_messages())

    def __repr__(self) -> str:  # pragma: no cover
        messages = self.get_generic_messages()
        return f"<{self.__class__.__name__}: messages={messages!r}>"
