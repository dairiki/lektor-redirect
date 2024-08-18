from __future__ import annotations

import pytest
from lektor.db import Pad

from lektor_redirect.util import nginx_quote_for_map, normalize_url_path, walk_records


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
def test_normalize_url_path(pad: Pad, url_path: str, normalized: str) -> None:
    record = pad.get("/about")
    assert normalize_url_path(record, url_path) == normalized


@pytest.mark.parametrize(
    "s, expected",
    [
        ("", ""),
        ("/foo/bar.html", "/foo/bar.html"),
        ('a"b', "'a\"b'"),
        ("/test run/", '"/test run/"'),
        ("include", r"\include"),
    ],
)
def test_nginx_quote_for_map(s: str, expected: str) -> None:
    assert nginx_quote_for_map(s) == expected


def test_walk_records(pad: Pad) -> None:
    paths = {record.path for record in walk_records(pad)}
    assert paths == {
        "/",
        "/about",
        "/images",
        "/projects",
        "/about/more-detail",
        "/images/apple-pie.jpg",
    }
