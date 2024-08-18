from __future__ import annotations

import re

from lektor.db import Pad

from lektor_redirect.exceptions import (
    RedirectConflictException,
    RedirectShadowsExistingRecordException,
    RedirectToSelfException,
)


def test_RedirectConflictException_message(pad: Pad) -> None:
    expected = (
        r"./foo. => <Page .*\bpath=./.*>: "
        r"conflicts with redirect ./foo. => <.*/about.*>\Z"
    )
    exc = RedirectConflictException("/foo", pad.root, pad.get("/about"))
    assert re.match(expected, exc.message())


def test_RedirectShadowsExistingRecordException_message(pad: Pad) -> None:
    expected = (
        r"./foo. => <Page .*\bpath=./.*>: "
        r".*conflicts with existing record <.*/about.*>\Z"
    )
    exc = RedirectShadowsExistingRecordException("/foo", pad.root, pad.get("/about"))
    assert re.match(expected, exc.message())


def test_RedirectToSelfException_message(pad: Pad) -> None:
    expected = r"./foo. => <Page .*\bpath=./.*>: redirect to self\Z"
    exc = RedirectToSelfException("/foo", pad.root)
    assert re.match(expected, exc.message())
