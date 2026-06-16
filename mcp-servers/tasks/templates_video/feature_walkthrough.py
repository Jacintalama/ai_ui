"""Caption style for the ``feature_walkthrough`` video template.

Data only: no logic. Differs from ``product_demo`` purely in style (slightly
smaller text, a tinted/denser band, a quicker crossfade). The render pipeline
shape is identical.
"""

# A calmer, slightly tighter caption for step-by-step feature tours.
STYLE = {
    "font_size_ratio": 0.044,        # font px = ratio * frame height
    "position": "bottom",            # one of: "bottom" | "center" | "top"
    "band_color": (15, 23, 42),      # RGB (slate) backing band
    "band_opacity": 0.60,            # 0..1 -> band alpha
    "fade_duration": 0.4,            # seconds, used by xfade between scenes
}
