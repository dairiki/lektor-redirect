import posixpath
import re
from collections import deque

from lektor.db import Page
from lektorlib.context import disable_dependency_recording


def normalize_url_path(record, url_path):
    """Normalize url_path.

    Returns a normalized, absolute url path.

    If url_path does not start with a /, it is interpreted relative to the url
    of record.

    """
    if not url_path.startswith("/"):
        url_path = posixpath.join(record.url_path, url_path)
    url_path = posixpath.normpath(url_path)
    if "." not in posixpath.basename(url_path):
        url_path += "/"
    return url_path


def nginx_quote_for_map(str):
    """Quote string, if necessary, for nginx map file."""
    quot = ""
    if re.search(r"[ \"'{};]", str):
        quot = '"'
        if quot in str and "'" not in str:
            quot = "'"

    escaped = re.sub(rf"[{quot}$\\]", r"\\\g<0>", str)
    if not quot and re.match(r"(default|hostnames|include|volatile)\b", escaped):
        # Nginx map "special parameters" must be escaped to prevent magic
        # See https://nginx.org/en/docs/http/ngx_http_map_module.html#map
        escaped = "\\" + escaped

    return f"{quot}{escaped}{quot}"


def walk_records(pad):
    """Iterate over all records in the Lektor DB."""
    with disable_dependency_recording():
        records = deque([pad.root])
        while records:
            record = records.popleft()
            if isinstance(record, Page):
                # XXX: Hack around the query API, for the sake of efficiency
                # We could stay within the official API be doing two queries:
                #
                #   records.extend(record.children.include_undiscoverable(True))
                #   records.extend(record.attachments.include_undiscoverable(True))
                #
                # This works, however, and is likely more efficient.
                query = record.children.include_undiscoverable(True)
                query._include_attachments = True
                records.extend(query)
            yield record
