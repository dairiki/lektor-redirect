import os
import re
import shutil
from contextlib import contextmanager, suppress

import pytest
from inifile import IniFile
from lektor import metaformat
from lektor.builder import Builder
from lektor.context import Context
from lektor.pluginsystem import get_plugin
from lektor.project import Project
from lektor.reporter import BufferReporter

from lektor_redirect import RedirectPlugin


@pytest.fixture(scope="session")
def site_dir_src():
    return os.path.join(os.path.dirname(__file__), "test-site")


@pytest.fixture
def tmp_site_dir(site_dir_src, tmp_path):
    site_dir = tmp_path / "site"
    shutil.copytree(site_dir_src, site_dir)
    return site_dir


@pytest.fixture
def project_url():
    return None


@pytest.fixture
def site_dir(request, site_dir_src, project_url):
    if project_url is not None:
        with request.getfixturevalue("open_site_config")() as inifile:
            inifile["project.url"] = project_url

    if "tmp_site_dir" in request.fixturenames:
        site_dir = request.getfixturevalue("tmp_site_dir")
    else:
        site_dir = site_dir_src
    return site_dir


@pytest.fixture
def env(site_dir):
    return Project.from_path(site_dir).make_env(load_plugins=False)


@pytest.fixture
def plugin(env):
    # Load our plugin
    env.plugin_controller.instanciate_plugin("redirect", RedirectPlugin)
    env.plugin_controller.emit("setup-env")
    return get_plugin(RedirectPlugin, env)


@pytest.fixture
def pad(env):
    return env.new_pad()


@pytest.fixture
def context(pad):
    with Context(pad=pad) as ctx:
        yield ctx


@pytest.fixture
def builder(pad, tmp_path):
    return Builder(pad, tmp_path / "output")


@pytest.fixture
def build_state(builder):
    with builder.new_build_state() as build_state:
        yield build_state


@pytest.fixture
def open_contents_lr(tmp_site_dir):
    @contextmanager
    def open_contents_lr(path):
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


@pytest.fixture
def open_config_file(tmp_site_dir):
    @contextmanager
    def open_config_file():
        filename = tmp_site_dir / "configs/redirect.ini"
        filename.parent.mkdir(exist_ok=True)
        inifile = IniFile(filename)
        yield inifile
        inifile.save()

    return open_config_file


@pytest.fixture
def open_site_config(tmp_site_dir):
    @contextmanager
    def open_site_config():
        filename = tmp_site_dir / "Test Site.lektorproject"
        inifile = IniFile(filename)
        yield inifile
        inifile.save()

    return open_site_config


@pytest.fixture
def redirect_map_disabled(open_config_file):
    with open_config_file() as inifile:
        with suppress(KeyError):
            del inifile["redirect.map_file"]


@pytest.fixture
def set_redirect_from(open_contents_lr):
    def set_redirect_from(path, url_paths):
        with open_contents_lr(path) as data:
            data["redirect_from"] = "\n".join(url_paths)

    return set_redirect_from


@pytest.fixture
def captured_reports(env):
    with Reporter(env) as reporter:
        yield reporter


class Reporter(BufferReporter):
    def get_generic_messages(self):
        return [
            data.get("message") for event, data in self.buffer if event == "generic"
        ]

    def message_matches(self, match):
        return any(re.match(match, message) for message in self.get_generic_messages())
