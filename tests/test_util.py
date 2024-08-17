import pytest

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
def test_normalize_url_path(pad, url_path, normalized):
    record = pad.get("/about")
    assert normalize_url_path(record, url_path) == normalized


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
def test_nginx_quote_for_map(str, expected):
    assert nginx_quote_for_map(str) == expected


def test_walk_records(pad):
    paths = {record.path for record in walk_records(pad)}
    assert paths == {
        "/",
        "/about",
        "/images",
        "/projects",
        "/about/more-detail",
        "/images/apple-pie.jpg",
    }
