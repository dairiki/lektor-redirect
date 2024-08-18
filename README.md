# lektor-redirect

[![PyPI version](https://img.shields.io/pypi/v/lektor-redirect.svg)](https://pypi.org/project/lektor-redirect/)
[![PyPI Supported Python Versions](https://img.shields.io/pypi/pyversions/lektor-redirect.svg)](https://pypi.python.org/pypi/lektor-redirect/)
[![GitHub license](https://img.shields.io/github/license/dairiki/lektor-redirect)](https://github.com/dairiki/lektor-redirect/blob/master/LICENSE)
[![GitHub Actions (Tests)](https://img.shields.io/github/actions/workflow/status/dairiki/lektor-redirect/ci.yml?branch=master&label=tests)](https://github.com/dairiki/lektor-redirect/)

This plugin allows pages (and attachments) to specify alternative/old
URLs which should redirect to their current location.

> [!IMPORTANT]
> Currently this plugin *will not work* on Lektor sites with [alternatives] enabled.

## How it works

The plugin looks for a field named (by default) `redirect_from` on pages
and attachments in the site. This field is expected to contain a sequence of URLs
to redirect from.

There are two ways that redirects may be implemented by this plugin.
Either or both may be enabled.

### Redirect pages

Redirect pages can be generated at the specified URLs.  The template for these
pages is up to you, however the intent is that these pages will attempt
an _[meta refresh]_ and/or _[javascript redirect]_ to the target page.

### Redirect map

A _redirect map_ file can be generated.  This may be used to configure your
web server to issue the desired redirects itself.
(Currently only an nginx-style map is supported.)


## Usage

By default the plugin looks for a field named `redirect_from` on pages in the
site.
(The name of the field may be customized in the plugin configuration file. See below.)
This field should contain a sequence of URLs to redirect from — most
likely it should have a field type of `strings`.

E.g. To be able to generate redirects to your pages, you might add the
following [field][field config] to your `models/page.ini` file:

```ini
[fields.redirect_from]
label = Redirect From
description = Other URLs which should redirect to this page
type = strings
```

The URLs in the `redirect_from` field may either be absolute (beginning)
with a slash (these are interpreted relative to the root of the site) or
they may be relative, in which case they are interpreted relative to the
URL of the parent of the page containing the `redirect_from` field.

As an example, if the is a page at lektor path `/blog/first-post`,
who’s URL, if nothing exotic is done with slug configuration is
`/blog/first-post/`, then, if `first-posts`’s `redirect_from` is set
to `test-post`, then:

- If redirect page generation is enabled, there will be an artifact
  generated at in `/blog/test-post/index.html` which will, hopefully,
  redirect the user to `/blog/first-post/`.

- If redirect map generation is enabled, it will include an entry
  mapping `/blog/test-post` to `/blog/first-post/`.

### Configuration File

The plugin's configuration file is `configs/redirect.ini`.
Settings should be in a `[redirect]` section.
There are currently three configurable settings. Here is an example:

```ini
[redirect]
# The name of the field from which redirects are extracted.
# The default value is "redirect_from"
redirect_from_field = redirect_from

# Set template used to render redirect pages.
# There is no default value — if no template is set, redirect
# page generation is disabled.
template = redirect.html

# Set the name of the redirect map file.
# There is no default value — if no value is set, redirect
# map generation is disabled.
map_file = .redirect.map
```

### Redirect Pages

If a `template` is configured in the plugin configuration file (`configs/redirect.ini`),
_redirect pages_ will be generated from the specified template. The intention is that
the resulting page will redirect the user to the target location using [meta refresh]
and/or a [javascript redirect].

Within the template, the target of the redirect is available as `this.target`.

An simple example for such a template is:

```jinja
<!doctype html>
<html>
  <head>
    <title>Page Moved</title>
    <link rel="canonical" href="{{ this.target|url(external=true) }}">

    <!-- meta refresh redirect -->
    <meta http-equiv="refresh" content="0; url={{ this.target|url(absolute=true) }}">

    <!-- javascript redirect -->
    <script type="text/javascript">
     window.location.href = {{ this.target|url(absolute=true)|tojson }};
    </script>
  </head>
  <body>
    <h1>Page Moved</h1>
    <p>
      If you are not automatically redirected, the page you want can be found at
      <a href="{{ this.target|url }}">{{ this.target|url(external=true) }}</a>.
    </p>
  </body>
</html>
```

> [!TIP]
> For the `url(external=true)` and `url(absolute=true)`
  filters to work, a `[url][project config]` may need to be configured
  for the project.

When redirecting from URLs that do not end with `.html` or `.htm`, the redirect page
is generated at the url with `/index.html` appended.
For example if there is a redirect from `/old-image.png` to
`/new-image.png`, the redirect page will be generated at
`/old-image.png/index.html`.
This is done with the hope that the web server, without extra
configuration, will respond to a request for `/old-image.png` with a
content-type header of `text/html`.

### Redirect Map

If a `map_file` is configured in the plugin configuration file (`configs/redirect.ini`),
a *map file* will be generated in the output tree.

The map file is in a format suitable for inclusion in an *nginx* [map block][nginx map].
Assuming there is a single redirect from `/old-page` to `/new-page`, the contents
of the map file would be:

```
/old-page/ /replacement-page/;
```

Assuming that `map_file` is set to `.redirect.map`, the salient parts
of an *nginx* configuration file that utilizes the redirect map might
look like:

```nginx
[...]

http {
    [...]

    # You may need to adjust this (and/or map_hash_max_size) to avoid
    # "could not build map_hash, you should increase map_hash_bucket_size"
    # error from nginx
    map_hash_bucket_size 128;

    map $uri $redirect_to_uri {
        default "";
        include /path/to/htdocs/.redirect.map;
    }

    server {
        listen [...];
        [...];

        root /path/to/htdocs;

        location ~ /\. {
            # Don't serve dot-files (like .redirect.map)
            return 404;
        }

        if ($redirect_to_uri) {
            # pass query args to preserve utm_* tracking parameters, etc.
            return 301 $redirect_to_uri$is_args$args;
        }

        [...]
    }
}
```

## To Do

- Make this work for Lektor projects with [alternatives] enabled.

- Add support for writing the redirect map file in other formats.
  (E.g. Apache [text map][apache text map] format.)

[alternatives]: https://www.getlektor.com/docs/content/alts/
[meta refresh]: https://developers.google.com/search/docs/crawling-indexing/301-redirects#metarefresh
[javascript redirect]: https://developers.google.com/search/docs/crawling-indexing/301-redirects#jslocation
[project config]: https://www.getlektor.com/docs/project/file/#project
[nginx map]: https://nginx.org/en/docs/http/ngx_http_map_module.html
[field config]: https://www.getlektor.com/docs/models/#fields
[apache text map]: https://httpd.apache.org/docs/current/rewrite/rewritemap.html#txt

## Author

Jeff Dairiki <dairiki@dairiki.org>
