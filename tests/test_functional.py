import os

import pytest
from lektor.builder import Builder
from lektor.project import Project
from lektor.reporter import CliReporter

from lektor_redirect import RedirectPlugin


@pytest.fixture(scope="module")
def demo_output(site_dir_src, tmp_path_factory):
    env = Project.from_path(site_dir_src).make_env(load_plugins=False)

    # Load our plugin
    env.plugin_controller.instanciate_plugin("redirect", RedirectPlugin)
    env.plugin_controller.emit("setup-env")

    pad = env.new_pad()
    output_path = tmp_path_factory.mktemp("demo-site-output")
    builder = Builder(pad, output_path)
    with CliReporter(env):
        failures = builder.build_all()
        assert failures == 0
    return output_path


def test_output_files(demo_output):
    # Look for the redirect pages generated by our redirect.html template
    redirectors = {
        os.fspath(p.relative_to(demo_output))
        for p in demo_output.rglob("*.html")
        if '<link rel="canonical"' in p.read_text()
    }
    assert redirectors == {
        "about/info/index.html",
        "details/index.html",
        "about/projects.html",
        "images/apple-cake.jpg/index.html",
    }


def test_redirect_map(demo_output):
    map_path = demo_output / ".redirect.map"
    assert map_path.read_text() == (
        "/about/info/ /about/more-detail/;\n"
        "/about/projects.html /projects/;\n"
        "/details/ /about/more-detail/;\n"
        "/images/apple-cake.jpg /images/apple-pie.jpg;\n"
    )
