"""The card asks for the file the route serves.

These live in different files and different languages, and they silently
disagreed once: the thumbnail was renamed from .png to .jpg in app_thumb and in
the route, and the rename missed the one place that matters, the <img> in the
card. Every request 404'd, the frame removed itself on error exactly as
designed, and the page looked untouched. Nothing failed loudly.

So the extension is asserted across all three, from the files themselves.
"""
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parents[1]


def _read(name):
    return (HERE / name).read_text(encoding="utf-8", errors="replace")


def test_the_card_requests_the_path_the_route_publishes():
    page = _read("static/projects.html")
    routes = _read("routes_projects.py")

    asked = set(re.findall(r"/thumb\.(\w+)", page))
    served = set(re.findall(r'@router\.get\("/\{slug\}/thumb\.(\w+)"\)', routes))

    assert asked, "the card stopped requesting a thumbnail at all"
    assert served, "the thumbnail route disappeared"
    assert asked == served, ("card asks for %s, route serves %s"
                             % (sorted(asked), sorted(served)))


def test_the_file_on_disk_has_the_same_extension():
    thumb = _read("app_thumb.py")
    stored = set(re.findall(r'"preview\.(\w+)"', thumb))
    routes = _read("routes_projects.py")
    served = set(re.findall(r'@router\.get\("/\{slug\}/thumb\.(\w+)"\)', routes))
    assert stored == served, ("stored as %s, served as %s"
                             % (sorted(stored), sorted(served)))


def test_the_declared_media_type_matches_the_extension():
    routes = _read("routes_projects.py")
    ext = re.findall(r'@router\.get\("/\{slug\}/thumb\.(\w+)"\)', routes)[0]
    assert ('media_type="image/%s"' % {"jpg": "jpeg"}.get(ext, ext)) in routes
