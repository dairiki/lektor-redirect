# lektor-redirect

This plugin allows pages to specify alternative/old URLs which should
redirect to their current location.

Redirect pages are generated at the specified URLs.  The template for these
pages is up to you, however the intent is that these pages will attempt
an _meta refresh_ and/or javascript redirect to the target page.

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
