# lektor-redirect

[![PyPI version](https://img.shields.io/pypi/v/lektor-redirect.svg)](https://pypi.org/project/lektor-redirect/)
[![PyPI Supported Python Versions](https://img.shields.io/pypi/pyversions/lektor-redirect.svg)](https://pypi.python.org/pypi/lektor-redirect/)
[![GitHub license](https://img.shields.io/github/license/dairiki/lektor-redirect)](https://github.com/dairiki/lektor-redirect/blob/master/LICENSE)
[![GitHub Actions (Tests)](https://img.shields.io/github/actions/workflow/status/dairiki/lektor-redirect/ci.yml?branch=master&label=tests)](https://github.com/dairiki/lektor-redirect/)

This plugin allows pages to specify alternative/old URLs which should
redirect to their current location.

## How it works

There are two ways that redirects may be implemented by this plugin.
Either or both may be enabled.

### Redirect pages

Redirect pages can be generated at the specified URLs.  The template for these
pages is up to you, however the intent is that these pages will attempt
an _meta refresh_ and/or javascript redirect to the target page.

### Redirect map

A _redirect map_ file can be generated.  This may be used to configure your
webserver to issue the desired redirects itself.
(Currently only an nginx-style map is supported.)

## Usage

By default the plugin looks for a field named `redirect_from` on pages in the
site.  This field should contain a sequence of URLs to redirect from — most
likely it should have a field type of `strings`.

The URLs in the `redirect_from` field may either be absolute (beginning)
with a slash (these are interpreted relative to the root of the site) or
they may be relative, in which case they are interpreted relative to the
URL of the parent of the page containing the `redirect_from` field.

As an example, if the is a page at lektor path `/blog/first-post`, who’s
URL, if nothing exotic is done with slug configuration is `/blog/first-post/`,
then, if `first-posts`’s `redirect_from` is set to `test-post`, there will
be a redirect generated in `/blog/test-post/index.html` which will hopefully
redirect the user to '/blog/first-post/'.

## Configuration

The plugin looks for configuration in it’s plugin config file:
`configs/redirect.ini`.  Settings should be in a `[redirect]` section.
There are currently to configurable settings.  Here are the defaults:

    [redirect]
    template = template.html
    redirect_from_field = redirect_from

## Caveats

Currently this plugin will not work on Lektor sites with [alts] enableds.

[alts]: https://www.getlektor.com/docs/content/alts/

## Author

Jeff Dairiki <dairiki@dairiki.org>
