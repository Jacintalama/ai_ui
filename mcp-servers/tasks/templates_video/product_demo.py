"""Caption style for the ``product_demo`` video template.

Data only: no logic. ``build_render_script`` / ``render_all_captions`` look this
up and apply it. Style parameters control only how captions look (font size,
position, backing band) and how long crossfades take; they never change the
render pipeline's shape.
"""

# A bold, high-contrast lower-third for a punchy product walkthrough.
STYLE = {
    "font_size_ratio": 0.050,        # font px = ratio * frame height
    "position": "bottom",            # one of: "bottom" | "center" | "top"
    "band_color": (0, 0, 0),         # RGB of the backing band
    "band_opacity": 0.55,            # 0..1 -> band alpha
    "fade_duration": 0.5,            # seconds, used by xfade between scenes
}
