"""
THIS IS THE FILE YOU IMPLEMENT.

Breakpoint reflow: scale in proportion when the aspect ratio is close;
rearrange into a row or column when it isn't. Same elements, no stretching.
"""

from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import ImageFont

# --- knobs you may want to tweak -------------------------------------------
RATIO_BOUNDARY = 1.35   # how far aspect may drift before we rearrange
MIN_UNIFORM = 0.45      # if everything would shrink more than this, rearrange
MIN_FONT = 12.0
MIN_GRID_ROW = 48.0
MARGIN_FRAC = 0.05      # padding as a fraction of the smaller canvas side
GAP_FRAC = 0.03
# ---------------------------------------------------------------------------


def resize(source: dict[str, Any], target_canvas: dict[str, Any]) -> dict[str, Any]:
    sw = float(source["canvas"]["width"])
    sh = float(source["canvas"]["height"])
    tw = float(target_canvas["width"])
    th = float(target_canvas["height"])

    elements = [deepcopy(el) for el in source["elements"]]

    sx, sy = tw / sw, th / sh
    uniform = min(sx, sy)
    stretch = max(sx / sy, sy / sx)

    if stretch <= RATIO_BOUNDARY and uniform >= MIN_UNIFORM:
        _similar(elements, sw, sh, tw, th, uniform, sx, sy)
    elif (tw / th) >= (sw / sh):
        _row(elements, sw, sh, tw, th)
    else:
        _column(elements, sw, sh, tw, th)

    for el in elements:
        _clamp(el, tw, th)
        if el["type"] == "text":
            el["font_size"] = max(1.0, float(el["font_size"]))

    return {
        "canvas": {
            "width": int(target_canvas["width"]),
            "height": int(target_canvas["height"]),
        },
        "elements": elements,
    }


# --- similar aspect: one scale, keep relative placement ----------------------

def _similar(elements, sw, sh, tw, th, s, sx, sy):
    for el in elements:
        if _is_bg(el, sw, sh):
            el["x"], el["y"] = 0.0, 0.0
            el["width"], el["height"] = tw, th
            continue
        cx = (el["x"] + el["width"] / 2.0) / sw
        cy = (el["y"] + el["height"] / 2.0) / sh
        if el["type"] == "text":
            el["width"] *= sx
            el["height"] *= sy
            el["font_size"] = max(MIN_FONT, el["font_size"] * s)
        else:
            el["width"] *= s
            el["height"] *= s
            if "corner_radius" in el:
                el["corner_radius"] *= s
        el["x"] = cx * tw - el["width"] / 2.0
        el["y"] = cy * th - el["height"] / 2.0


# --- past the boundary: rearrange --------------------------------------------

def _row(elements, sw, sh, tw, th):
    if tw / th >= 1.0:
        if tw / th <= 1.3:
            _compose_portrait(elements, sw, sh, tw, th)
        else:
            _compose_banner(elements, sw, sh, tw, th)
        return

    """Wide/short canvas: use a half-width image panel with readable overlays."""
    if th <= 160:
        margin = max(2.0, th * 0.02)
        gap = max(1.0, th * 0.015)
    else:
        margin = max(8.0, min(tw, th) * MARGIN_FRAC)
        gap = max(6.0, min(tw, th) * GAP_FRAC)
    inner_h = max(1.0, th - 2 * margin)
    bgs, units = _units(elements, sw, sh)
    _fill_bgs(bgs, tw, th)

    logos = [u for u in units if _is_logo(u)]
    units = [u for u in units if not _is_logo(u)]
    if logos and th > 160:
        logo = logos.pop(0)
        logo_aspect = logo["w"] / max(logo["h"], 1.0)
        logo_w = min(tw * 0.18, inner_h * 0.10 * logo_aspect)
        logo_h = logo_w / max(logo_aspect, 1e-6)
        _place_unit(logo, tw - margin - logo_w, margin, logo_w, logo_h)
        units.extend(logos)

    texts = [u for u in units if u["is_text"]]
    others = [u for u in units if not u["is_text"]]
    others.sort(key=lambda u: (u["y"], u["x"]))

    images = [
        unit for unit in others
        if len(unit["members"]) == 1 and unit["members"][0]["type"] == "image"
    ]
    hero = max(images, key=lambda unit: unit["w"] * unit["h"], default=None)
    if hero is not None:
        others.remove(hero)
        hero_element = hero["members"][0]
        panel_w = tw * 0.5
        lower_z = max(
            (el.get("z_index", 0) for el in bgs),
            default=min(
                (member.get("z_index", 0)
                 for unit in units for member in unit["members"]),
                default=0,
            ) - 1,
        )
        hero_element["z_index"] = lower_z + 1
        if th > 160:
            image_slot_x = panel_w * 0.5
            image_slot_w = panel_w - image_slot_x - margin
            scale = min(
                image_slot_w / max(hero["w"], 1e-6),
                (th - 2 * margin) / max(hero["h"], 1e-6),
            )
            image_w, image_h = hero["w"] * scale, hero["h"] * scale
            hero_element["x"] = image_slot_x + (image_slot_w - image_w) / 2.0
            hero_element["y"] = (th - image_h) / 2.0
            hero_element["width"], hero_element["height"] = image_w, image_h
            hero_element["fit"] = "contain"

        legal = [
            unit for unit in texts
            if any("legal" in str(member.get("id", "")).lower()
                   for member in unit["members"])
        ]
        texts = [unit for unit in texts if unit not in legal]
        footer_h = min(20.0, th * 0.24) if legal and th <= 160 else 0.0
        footer_gap = max(1.0, th * 0.015) if footer_h else 0.0
        overlay_h = max(1.0, inner_h - footer_h - footer_gap)
        heading = None
        paragraph = None

        if texts:
            heading = max(
                texts,
                key=lambda unit: max(
                    float(member.get("font_size", 0))
                    for member in unit["members"]
                ),
            )
            following = [
                unit for unit in texts
                if unit is not heading and unit["y"] >= heading["y"]
            ]
            paragraph = min(following, key=lambda unit: unit["y"], default=None)
            overlay = [heading]
            if paragraph is not None:
                overlay.append(paragraph)
            texts = [unit for unit in texts if unit not in overlay]

            overlay_x = margin
            overlay_w = max(1.0, panel_w - 2 * margin)
            overlay_gap = max(2.0, inner_h * 0.04)
            heading_share = 0.52 if th <= 160 else 0.55
            heading_h = max(1.0, (overlay_h - overlay_gap) * heading_share)
            paragraph_h = max(1.0, overlay_h - overlay_gap - heading_h)
            if th > 160:
                _place_unit(
                    heading, overlay_x, margin, overlay_w, heading_h
                )
                for member in heading["members"]:
                    member["z_index"] = max(
                        member.get("z_index", 0), hero_element["z_index"] + 1
                    )
            if paragraph is not None:
                if th > 160:
                    text_w = max(1.0, panel_w * 0.44)
                    text_x = margin
                    text_gap = max(8.0, inner_h * 0.04)
                    heading_h = max(1.0, inner_h * 0.4)
                    paragraph_y = margin + heading_h + text_gap
                    paragraph_h = max(
                        1.0, th - margin - paragraph_y
                    )
                    _place_unit(
                        heading, text_x, margin, text_w, heading_h
                    )
                    _place_unit(
                        paragraph, text_x, paragraph_y, text_w, paragraph_h
                    )
                    for unit in (heading, paragraph):
                        for member in unit["members"]:
                            member["z_index"] = max(
                                member.get("z_index", 0),
                                hero_element["z_index"] + 1,
                            )
                    texts = [
                        unit for unit in texts
                        if unit not in (heading, paragraph)
                    ]

        if th <= 160:
            compact_units = sorted(
                logos + others + texts, key=lambda unit: (unit["y"], unit["x"])
            )
            _place_short_banner(
                hero, bgs, compact_units, heading, paragraph, legal,
                tw, th,
            )
            return

        content_x = panel_w + margin
        inner_w = max(1.0, tw - content_x - margin)
    else:
        content_x = margin
        inner_w = max(1.0, tw - 2 * margin)

    for u in others:
        h = inner_h * 0.72
        aspect = u["w"] / max(u["h"], 1)
        u["pw"], u["ph"] = h * aspect, h

    n = len(others) + (1 if texts else 0)
    gaps = gap * max(0, n - 1)
    others_w = sum(u["pw"] for u in others)
    text_w = max(inner_w * 0.35, 120.0) if texts else 0.0
    budget = max(1.0, inner_w - gaps)
    if others_w + text_w > budget and others_w > 0:
        scale = max(0.25, (budget - text_w) / others_w)
        for u in others:
            u["pw"] *= scale
            u["ph"] *= scale
        others_w = sum(u["pw"] for u in others)
    if texts:
        text_w = max(80.0, budget - others_w)

    x = content_x
    placed_text = False
    first_image_done = False
    for u in others:
        y = margin + (inner_h - u["ph"]) / 2.0
        _place_unit(u, x, y, min(u["pw"], max(1.0, tw - margin - x)), u["ph"])
        x += u["pw"] + gap
        if _looks_like_image(u):
            first_image_done = True
        if texts and not placed_text and first_image_done:
            _place_text_column(texts, x, margin, text_w, inner_h)
            x += text_w + gap
            placed_text = True
    if texts and not placed_text:
        _place_text_column(texts, x, margin, text_w, inner_h)


def _compose_banner(elements, sw, sh, tw, th):
    bgs, units = _units(elements, sw, sh)
    _fill_bgs(bgs, tw, th)

    logos = [unit for unit in units if _is_logo(unit)]
    content = [unit for unit in units if unit not in logos]
    images = [
        unit for unit in content
        if len(unit["members"]) == 1
        and unit["members"][0]["type"] == "image"
    ]
    hero = max(images, key=lambda unit: unit["w"] * unit["h"], default=None)
    if hero is not None:
        content.remove(hero)

    all_text_units = [unit for unit in content if unit["is_text"]]
    text_units = list(all_text_units)
    legal = [unit for unit in text_units if _is_legal(unit)]
    text_units = [unit for unit in text_units if unit not in legal]
    heading = max(
        text_units,
        key=lambda unit: max(
            float(member.get("font_size", 0)) for member in unit["members"]
        ),
        default=None,
    )
    paragraphs = sorted(
        (unit for unit in text_units if unit is not heading),
        key=lambda unit: (unit["y"], unit["x"]),
    )
    controls = [
        unit for unit in content
        if not unit["is_text"]
        and any(member["type"] == "text" for member in unit["members"])
    ]
    decorations = [
        unit for unit in content
        if unit not in controls and unit not in images and unit not in all_text_units
    ]

    if th <= 160:
        _compose_short_banner(
            tw, th, logos, hero, images, controls, heading, paragraphs,
            legal, decorations,
        )
        return

    margin = max(8.0, min(tw, th) * 0.06)
    left_x = margin
    left_w = tw * 0.50
    hero_x = tw * 0.61
    hero_w = tw * 0.27
    hero_h = th * 0.88
    hero_y = (th - hero_h) / 2.0
    if hero is not None:
        _place_image_unit(hero, hero_x, hero_y, hero_w, hero_h)

    if logos:
        logo = max(logos, key=lambda unit: unit["w"] * unit["h"])
        _place_image_unit(
            logo, tw - margin - tw * 0.16, margin * 0.45,
            tw * 0.16, min(th * 0.18, 72.0),
        )
        logos.remove(logo)
    for index, logo in enumerate(logos):
        _place_image_unit(
            logo, tw - margin - tw * 0.16,
            margin * 0.45 + (index + 1) * min(th * 0.18, 72.0),
            tw * 0.16, min(th * 0.18, 72.0),
        )

    remaining_images = [unit for unit in images if unit is not hero]
    for index, image in enumerate(remaining_images):
        _place_image_unit(
            image, tw - margin - 48.0, th * 0.42 + index * 52.0, 40.0, 40.0
        )

    top_controls = sorted(
        (unit for unit in controls if not _is_call_to_action(unit)),
        key=lambda unit: (unit["x"], unit["y"]),
    )
    calls_to_action = [
        unit for unit in controls if _is_call_to_action(unit)
    ]
    if not calls_to_action and controls:
        calls_to_action = [max(controls, key=lambda unit: unit["y"])]
        top_controls = [unit for unit in controls if unit not in calls_to_action]

    control_y = margin * 0.5
    control_h = min(46.0, th * 0.13)
    control_gap = 12.0
    control_w = min(220.0, (left_w - control_gap * max(0, len(top_controls) - 1)) /
                    max(1, len(top_controls)))
    for index, unit in enumerate(top_controls):
        _place_group_unit(
            unit, left_x + index * (control_w + control_gap), control_y,
            control_w, control_h,
        )

    title_y = margin + control_h + 18.0
    title_h = min(th * 0.25, 100.0)
    if heading is not None:
        _place_text_unit(
            heading, left_x, title_y, left_w, title_h,
            max_size=min(56.0, _unit_font_size(heading)),
            min_size=8.0 if tw < 500 else 14.0,
        )

    cta_y = th - margin - min(66.0, th * 0.18)
    cta_h = min(66.0, th * 0.18)
    cta_w = min(340.0, left_w * 0.65)
    for index, unit in enumerate(calls_to_action):
        _place_group_unit(
            unit, left_x + index * (cta_w + control_gap),
            cta_y, cta_w, cta_h,
        )

    paragraph_top = title_y + title_h + 8.0
    paragraph_bottom = cta_y - 10.0
    paragraph_h = max(1.0, (paragraph_bottom - paragraph_top) /
                      max(1, len(paragraphs)))
    for index, unit in enumerate(paragraphs):
        _place_text_unit(
            unit, left_x, paragraph_top + index * paragraph_h,
            left_w, paragraph_h,
            max_size=min(24.0, _unit_font_size(unit)),
            min_size=6.0 if tw < 500 else 8.0,
        )

    for index, unit in enumerate(legal):
        _place_text_unit(
            unit, margin, th - max(16.0, margin * 0.45) - index * 18.0,
            tw * 0.48, 16.0, max_size=12.0, min_size=7.0,
        )

    for index, unit in enumerate(decorations):
        size = min(96.0, th * 0.24, max(unit["w"], unit["h"]) * 0.25)
        x = hero_x - size * 0.45 if index % 2 == 0 else hero_x + hero_w - size * 0.55
        y = hero_y + index * size * 0.55
        _place_group_unit(unit, x, y, size, size)


def _compose_short_banner(
    tw, th, logos, hero, images, controls, heading, paragraphs, legal,
    decorations,
):
    margin = max(2.0, th * 0.025)
    if tw <= 400:
        title_y, title_h = margin, th * 0.24
        paragraph_y, paragraph_h = th * 0.26, th * 0.26 / max(1, len(paragraphs))
        text_w = tw * 0.83 - margin
        hero_x, hero_w = tw * 0.86, tw * 0.08
        logo_w, logo_h = tw * 0.08, th * 0.12
        control_y, control_h = th * 0.57, th * 0.30
        legal_y = th * 0.88
    else:
        title_y, title_h = margin, th * 0.54
        paragraph_y, paragraph_h = margin, th * 0.54 / max(1, len(paragraphs))
        text_w = tw * 0.39
        hero_x, hero_w = tw * 0.45, tw * 0.08
        logo_w, logo_h = tw * 0.10, th * 0.22
        control_y, control_h = th * 0.60, th * 0.27
        legal_y = th * 0.89

    if hero is not None:
        _place_image_unit(hero, hero_x, th * 0.27, hero_w, th * 0.31)
    for index, logo in enumerate(logos):
        _place_image_unit(
            logo, tw - margin - logo_w, margin + index * (logo_h + 1.0),
            logo_w, logo_h,
        )

    if heading is not None:
        _place_text_unit(
            heading, margin, title_y, text_w, title_h,
            max_size=min(14.0, _unit_font_size(heading)), min_size=3.5,
        )
    for index, unit in enumerate(paragraphs):
        x = margin if tw <= 400 else tw * 0.56
        width = text_w if tw <= 400 else tw * 0.30
        _place_text_unit(
            unit, x, paragraph_y + index * paragraph_h,
            max(1.0, width), paragraph_h,
            max_size=min(10.0, _unit_font_size(unit)), min_size=3.5,
        )

    for index, image in enumerate(unit for unit in images if unit is not hero):
        _place_image_unit(
            image, tw * 0.96 - index * th * 0.13,
            th * 0.35, th * 0.035, th * 0.13,
        )

    control_h = max(1.0, control_h)
    control_gap = max(1.0, tw * 0.006)
    cell_w = max(
        1.0,
        (tw - 2.0 * margin - control_gap * max(0, len(controls) - 1)) /
        max(1, len(controls)),
    )
    for index, unit in enumerate(sorted(controls, key=lambda item: (item["y"], item["x"]))):
        for member in unit["members"]:
            member["rotation"] = 0
        _place_group_unit(
            unit, margin + index * (cell_w + control_gap),
            control_y, cell_w, control_h,
        )

    legal_h = max(1.0, th - legal_y - margin)
    for index, unit in enumerate(legal):
        _place_text_unit(
            unit, margin, legal_y - index * legal_h, tw - 2.0 * margin,
            legal_h, max_size=6.0,
            min_size=3.0 if tw <= 400 and th <= 60 else 4.0,
        )

    for index, unit in enumerate(decorations):
        size = max(1.0, min(th * 0.12, tw * 0.04))
        _place_group_unit(
            unit, hero_x - size * 0.25, margin + index * size * 0.4,
            size, size,
        )


def _place_image_unit(unit, x, y, w, h):
    member = unit["members"][0]
    aspect = float(member["width"]) / max(float(member["height"]), 1e-6)
    image_w = min(w, h * aspect)
    image_h = image_w / max(aspect, 1e-6)
    member["x"] = x + (w - image_w) / 2.0
    member["y"] = y + (h - image_h) / 2.0
    member["width"], member["height"] = image_w, image_h
    member["fit"] = "contain"


def _place_group_unit(unit, x, y, w, h):
    _place_unit(unit, x, y, w, h)
    for member in unit["members"]:
        if member["type"] == "text":
            minimum = 3.0 if w <= 400 and h <= 60 else min(
                4.0, float(member["font_size"])
            )
            _fit_text_to_box(
                member, member["x"], member["y"], member["width"],
                member["height"], max_size=float(member["font_size"]),
                min_size=minimum,
            )


def _place_text_unit(unit, x, y, w, h, max_size, min_size):
    if len(unit["members"]) == 1:
        _fit_text_to_box(unit["members"][0], x, y, w, h, max_size, min_size)
    else:
        _place_unit(unit, x, y, w, h)
        for member in unit["members"]:
            _fit_text_to_box(
                member, member["x"], member["y"], member["width"],
                member["height"], float(member["font_size"]),
                min(min_size, float(member["font_size"])),
            )


def _fit_text_to_box(element, x, y, w, h, max_size, min_size):
    element["x"], element["y"] = x, y
    element["width"], element["height"] = max(1.0, w), max(1.0, h)
    desired = max(1.0, min(float(element.get("font_size", max_size)), max_size))
    minimum = max(1.0, min(desired, min_size))
    low, high = minimum, desired
    for _ in range(16):
        size = (low + high) / 2.0
        if _text_fits(element, size, element["width"], element["height"]):
            low = size
        else:
            high = size
    element["font_size"] = max(minimum, low)


def _text_fits(element, size, width, height):
    font = _layout_font(
        str(element.get("font_family", "Solstice Sans")),
        str(element.get("font_weight", "regular")),
        str(element.get("font_style", "normal")),
        max(1, round(size)),
    )
    content = str(element.get("content", ""))
    lines = 0
    for paragraph in content.split("\n"):
        line_width = 0.0
        for word in paragraph.split(" "):
            word_width = font.getlength(word)
            next_width = line_width + (font.getlength(" ") if line_width else 0.0) + word_width
            if line_width and next_width > width * 0.96:
                lines += 1
                line_width = word_width
            else:
                line_width = next_width
        lines += 1
    line_height = float(element.get("line_height", 1.2))
    max_lines = element.get("max_lines")
    return (
        lines * size * line_height <= height
        and (max_lines is None or lines <= int(max_lines))
    )


@lru_cache(maxsize=256)
def _layout_font(family, weight, style, size):
    family_name = "".join(str(family).split()).lower()
    prefix = "SolsticeSerif" if "serif" in family_name else "SolsticeSans"
    bold = str(weight).lower() in {"bold", "semibold", "extrabold", "black"}
    italic = str(style).lower() == "italic"
    suffix = "Bold" if bold else "Regular"
    if italic:
        suffix += "Italic"
    font_path = (
        Path(__file__).resolve().parent.parent
        / "brand_kit" / "fonts" / f"{prefix}-{suffix}.ttf"
    )
    if not font_path.is_file():
        font_path = font_path.with_name(f"{prefix}-Regular.ttf")
    return ImageFont.truetype(str(font_path), size)


def _unit_font_size(unit):
    return max(
        (float(member.get("font_size", 12.0)) for member in unit["members"]),
        default=12.0,
    )


def _unit_text(unit):
    return " ".join(
        str(member.get("content", "")) for member in unit["members"]
        if member["type"] == "text"
    ).lower()


def _unit_ids(unit):
    return " ".join(str(member.get("id", "")) for member in unit["members"]).lower()


def _is_call_to_action(unit):
    text = _unit_text(unit)
    return any(token in text for token in ("shop", "buy", "order", "visit", "learn more"))


def _is_legal(unit):
    text = _unit_text(unit)
    ids = " ".join(str(member.get("id", "")) for member in unit["members"]).lower()
    return "legal" in ids or "responsibly" in text or "void where prohibited" in text


def _place_compact_unit(unit, x, y, w, h):
    for member in unit["members"]:
        if float(member.get("rotation", 0)):
            member["rotation"] = 0
        if member["type"] == "text":
            member["x"] = x + 2.0
            member["y"] = y
            member["width"] = max(1.0, w - 4.0)
            member["height"] = h
            member["font_size"] = 8.0
        else:
            if member["type"] == "image":
                aspect = float(member["width"]) / max(float(member["height"]), 1e-6)
                image_w = min(w, h * aspect)
                image_h = image_w / max(aspect, 1e-6)
                member["x"] = x + (w - image_w) / 2.0
                member["y"] = y + (h - image_h) / 2.0
                member["width"], member["height"] = image_w, image_h
                member["fit"] = "contain"
            else:
                member["x"], member["y"] = x, y
                member["width"], member["height"] = w, h
            if "corner_radius" in member:
                member["corner_radius"] = min(
                    h / 2.0, float(member["corner_radius"])
                )


def _place_short_banner(hero, backgrounds, units, heading, paragraph, legal, tw, th):
    margin = max(1.0, th * 0.02)
    hero_element = hero["members"][0]
    background_z = max(
        (el.get("z_index", 0) for el in backgrounds),
        default=min(
            (member.get("z_index", 0)
             for unit in units for member in unit["members"]),
            default=0,
        ) - 1,
    )
    hero_element["z_index"] = max(
        hero_element.get("z_index", 0), background_z + 1
    )
    if not backgrounds:
        hero_element["x"], hero_element["y"] = 0.0, 0.0
        hero_element["width"], hero_element["height"] = tw, th
        hero_element["fit"] = "cover"

    text_y = margin
    text_h = max(1.0, th * 0.57)
    text_w = max(1.0, tw * 0.41)
    for index, unit in enumerate((heading, paragraph)):
        if unit is None:
            continue
        x = margin if index == 0 else tw - margin - text_w
        _place_unit(unit, x, text_y, text_w, text_h)
        for member in unit["members"]:
            member["z_index"] = max(
                member.get("z_index", 0), hero_element["z_index"] + 1
            )
            member["font_size"] = min(
                float(member.get("font_size", MIN_FONT)), 8.0
            )

    supporting_units = [
        unit for unit in units
        if unit is not heading and unit is not paragraph
    ]
    middle_images = [
        unit for unit in supporting_units if _looks_like_image(unit)
    ]
    if backgrounds:
        middle_images.append(hero)
    support_units = [
        unit for unit in supporting_units if unit not in middle_images
    ]
    support_gap = max(1.0, tw * 0.005)
    support_y = th * 0.66
    support_h = th * 0.16
    footer_y = th * 0.82
    footer_h = max(1.0, th - footer_y - margin)
    image_gap = max(1.0, th * 0.015)
    image_w = tw * 0.18
    image_x = (tw - image_w) / 2.0
    main_images = [unit for unit in middle_images if unit is hero]
    small_images = [unit for unit in middle_images if unit is not hero]
    image_y = margin
    if small_images:
        small_h = max(
            1.0,
            (th * 0.26 - image_gap * max(0, len(small_images) - 1))
            / len(small_images),
        )
        for unit in small_images:
            _place_compact_unit(
                unit, image_x, image_y, image_w, small_h
            )
            image_y += small_h + image_gap
            for member in unit["members"]:
                member["z_index"] = max(
                    member.get("z_index", 0), hero_element["z_index"] + 1
                )
    for unit in main_images:
        main_h = max(1.0, th * 0.30)
        _place_compact_unit(
            unit, image_x, (th - main_h) / 2.0, image_w, main_h
        )
        for member in unit["members"]:
            member["z_index"] = max(
                member.get("z_index", 0), hero_element["z_index"]
            )
    if support_units:
        cell_w = (tw - 2 * margin - support_gap * (len(support_units) - 1)) / len(support_units)
        for index, unit in enumerate(support_units):
            _place_compact_unit(
                unit,
                margin + index * (cell_w + support_gap),
                support_y,
                cell_w,
                support_h,
            )
            for member in unit["members"]:
                member["z_index"] = max(
                    member.get("z_index", 0), hero_element["z_index"] + 1
                )

    for unit in legal:
        _place_compact_unit(unit, margin, footer_y, tw - 2 * margin, footer_h)
        for member in unit["members"]:
            if member["type"] == "text":
                member["font_size"] = min(
                    float(member.get("font_size", MIN_FONT)), 8.0
                )
                member["z_index"] = max(
                    member.get("z_index", 0), hero_element["z_index"] + 1
                )


def _column(elements, sw, sh, tw, th):
    """Tall canvas: pin the logo, then stack content in responsive grid rows."""
    if tw / th <= 0.68:
        _compose_portrait(elements, sw, sh, tw, th)
        return

    margin = max(8.0, min(tw, th) * MARGIN_FRAC)
    gap = max(6.0, min(tw, th) * GAP_FRAC)
    inner_w, inner_h = tw - 2 * margin, th - 2 * margin
    bgs, units = _units(elements, sw, sh)
    _promote_background(bgs, units)
    _fill_bgs(bgs, tw, th)
    units.sort(key=lambda u: (u["y"], u["x"]))

    logos = [u for u in units if _is_logo(u)]
    units = [u for u in units if not _is_logo(u)]
    logo_height = 0.0
    if logos:
        logo = logos.pop(0)
        logo_aspect = logo["w"] / max(logo["h"], 1.0)
        logo_w = min(inner_w * 0.38, inner_h * 0.10 * logo_aspect)
        logo_h = logo_w / max(logo_aspect, 1e-6)
        _place_unit(logo, tw - margin - logo_w, margin, logo_w, logo_h)
        logo_height = logo_h + gap
        units.extend(logos)

    # Short grouped units (for example, badges) share a row instead of
    # being reduced to a narrow full-width column.
    rows = []
    index = 0
    while index < len(units):
        unit = units[index]
        compact = unit["members"][0].get("group_id") and unit["h"] <= sh * 0.06
        if compact and index + 1 < len(units):
            next_unit = units[index + 1]
            next_compact = (
                next_unit["members"][0].get("group_id")
                and next_unit["h"] <= sh * 0.06
            )
            if next_compact:
                rows.append([unit, next_unit])
                index += 2
                continue
        rows.append([unit])
        index += 1

    shares = [max(unit["h"] for unit in row) for row in rows]
    total = sum(shares) or 1.0
    available_h = max(1.0, inner_h - logo_height)
    gaps = gap * max(0, len(rows) - 1)
    budget = max(1.0, available_h - gaps)
    row_floor = min(MIN_GRID_ROW, budget / max(1, len(rows)))
    extra_height = max(0.0, budget - row_floor * len(rows))
    row_heights = [
        row_floor + extra_height * (share / total)
        for share in shares
    ]

    y = margin + logo_height
    for row, h in zip(rows, row_heights):
        if len(row) == 2:
            cell_w = (inner_w - gap) / 2.0
            for column, unit in enumerate(row):
                _place_unit(unit, margin + column * (cell_w + gap), y, cell_w, h)
        else:
            unit = row[0]
            if unit["is_text"]:
                w, x = inner_w, margin
            else:
                aspect = unit["w"] / max(unit["h"], 1)
                w = min(inner_w, h * aspect)
                x = margin + (inner_w - w) / 2.0
            _place_unit(unit, x, y, w, h)
        y += h + gap


def _compose_portrait(elements, sw, sh, tw, th):
    bgs, units = _units(elements, sw, sh)
    _fill_bgs(bgs, tw, th)

    logos = [unit for unit in units if _is_logo(unit)]
    content = [unit for unit in units if unit not in logos]
    images = [
        unit for unit in content
        if len(unit["members"]) == 1
        and unit["members"][0]["type"] == "image"
    ]
    hero = max(images, key=lambda unit: unit["w"] * unit["h"], default=None)
    if hero is not None:
        content.remove(hero)

    text_units = [unit for unit in content if unit["is_text"]]
    legal = [unit for unit in text_units if _is_legal(unit)]
    text_units = [unit for unit in text_units if unit not in legal]
    heading = max(
        text_units,
        key=lambda unit: max(
            float(member.get("font_size", 0)) for member in unit["members"]
        ),
        default=None,
    )
    paragraphs = sorted(
        (unit for unit in text_units if unit is not heading),
        key=lambda unit: (unit["y"], unit["x"]),
    )
    controls = [
        unit for unit in content
        if not unit["is_text"]
        and any(member["type"] == "text" for member in unit["members"])
    ]
    calls_to_action = [unit for unit in controls if _is_call_to_action(unit)]
    other_controls = [unit for unit in controls if unit not in calls_to_action]
    ribbons = [
        unit for unit in other_controls
        if "ribbon" in _unit_ids(unit) or "sale" in _unit_text(unit)
    ]
    badges = [unit for unit in other_controls if unit not in ribbons]
    decorations = [
        unit for unit in content
        if unit not in controls and unit not in images and unit not in text_units
        and unit not in legal
    ]
    remaining_images = [unit for unit in images if unit is not hero]

    margin = max(10.0, min(tw, th) * 0.05)
    for index, logo in enumerate(logos):
        logo_w = tw * 0.30
        logo_h = min(th * 0.055, logo_w / max(logo["w"] / max(logo["h"], 1.0), 1e-6))
        _place_image_unit(
            logo, (tw - logo_w) / 2.0, margin * 0.35 + index * (logo_h + 2.0),
            logo_w, logo_h,
        )

    for index, ribbon in enumerate(ribbons):
        ribbon_w = tw * 0.46
        _place_group_unit(
            ribbon, margin, th * 0.075 + index * th * 0.07,
            ribbon_w, th * 0.065,
        )

    hero_y = th * 0.14
    hero_h = th * 0.21
    if hero is not None:
        _place_image_unit(hero, tw * 0.36, hero_y, tw * 0.28, hero_h)
    for index, image in enumerate(remaining_images):
        image_size = min(tw * 0.12, th * 0.05)
        _place_image_unit(
            image, tw - margin - image_size, th * 0.24 + index * image_size,
            image_size, image_size,
        )

    title_y = th * 0.34
    title_h = th * 0.15
    if heading is not None:
        _place_text_unit(
            heading, margin, title_y, tw - 2.0 * margin, title_h,
            max_size=min(32.0, _unit_font_size(heading)), min_size=9.0,
        )

    paragraph_y = th * 0.49
    paragraph_h = th * 0.15 / max(1, len(paragraphs))
    for index, unit in enumerate(paragraphs):
        _place_text_unit(
            unit, margin, paragraph_y + index * paragraph_h,
            tw - 2.0 * margin, paragraph_h,
            max_size=min(18.0, _unit_font_size(unit)), min_size=7.0,
        )

    badge_rows = [
        badges[index:index + 3] for index in range(0, len(badges), 3)
    ]
    badge_y = th * 0.63
    badge_h = max(20.0, th * 0.10)
    badge_gap = max(4.0, tw * 0.02)
    for row_index, row in enumerate(badge_rows):
        cell_w = (tw - 2.0 * margin - badge_gap * max(0, len(row) - 1)) / len(row)
        for column, unit in enumerate(row):
            _place_group_unit(
                unit, margin + column * (cell_w + badge_gap),
                badge_y + row_index * (badge_h + badge_gap),
                cell_w, badge_h,
            )

    cta_y = th * 0.81
    cta_h = th * 0.085
    cta_gap = max(6.0, tw * 0.025)
    cta_w = min(tw * 0.72, (tw - 2.0 * margin - cta_gap * max(0, len(calls_to_action) - 1)) /
                max(1, len(calls_to_action)))
    for index, unit in enumerate(calls_to_action):
        _place_group_unit(
            unit, (tw - (len(calls_to_action) * cta_w +
                         max(0, len(calls_to_action) - 1) * cta_gap)) / 2.0
            + index * (cta_w + cta_gap),
            cta_y, cta_w, cta_h,
        )

    legal_y = th * 0.92
    legal_h = max(1.0, th - legal_y - margin * 0.3)
    for index, unit in enumerate(legal):
        _place_text_unit(
            unit, margin, legal_y + index * legal_h,
            tw - 2.0 * margin, legal_h,
            max_size=10.0, min_size=5.0,
        )

    for index, unit in enumerate(decorations):
        size = min(tw * 0.07, th * 0.035)
        x = margin if index % 2 == 0 else tw - margin - size
        _place_group_unit(unit, x, th * 0.28 + index * size, size, size)


def _place_text_column(texts, x, y, w, h):
    texts = sorted(texts, key=lambda u: u["y"])
    gap = max(4.0, h * 0.05)
    budget = max(1.0, h - gap * max(0, len(texts) - 1))
    total = sum(u["h"] for u in texts) or 1.0
    cy = y
    for u in texts:
        uh = budget * (u["h"] / total)
        _place_unit(u, x, cy, w, uh)
        cy += uh + gap


# --- units: groups stay glued; background is separate ------------------------

def _units(elements, sw, sh):
    bgs, grouped, singles = [], {}, []
    for el in elements:
        if _is_bg(el, sw, sh):
            bgs.append(el)
            continue
        gid = el.get("group_id")
        if gid:
            grouped.setdefault(gid, []).append(el)
        else:
            singles.append(el)

    units = []
    for members in grouped.values():
        units.append(_make_unit(members))
    for el in singles:
        units.append(_make_unit([el]))
    return bgs, units


def _make_unit(members):
    x0 = min(m["x"] for m in members)
    y0 = min(m["y"] for m in members)
    x1 = max(m["x"] + m["width"] for m in members)
    y1 = max(m["y"] + m["height"] for m in members)
    return {
        "members": members,
        "x": x0,
        "y": y0,
        "w": x1 - x0,
        "h": y1 - y0,
        "is_text": all(m["type"] == "text" for m in members),
    }


def _place_unit(unit, x, y, w, h):
    members = unit["members"]
    ox, oy = unit["x"], unit["y"]
    ow, oh = max(unit["w"], 1e-6), max(unit["h"], 1e-6)
    s = min(w / ow, h / oh)
    if unit["is_text"]:
        sx, sy = w / ow, h / oh
        s_font = min(sx, sy)
        for el in members:
            el["x"] = x + (el["x"] - ox) * sx
            el["y"] = y + (el["y"] - oy) * sy
            el["width"] *= sx
            el["height"] *= sy
            el["font_size"] = max(MIN_FONT, el["font_size"] * s_font)
        return
    used_w, used_h = ow * s, oh * s
    px = x + (w - used_w) / 2.0
    py = y + (h - used_h) / 2.0
    for el in members:
        el["x"] = px + (el["x"] - ox) * s
        el["y"] = py + (el["y"] - oy) * s
        el["width"] *= s
        el["height"] *= s
        if "corner_radius" in el:
            el["corner_radius"] *= s
        if el["type"] == "text":
            el["font_size"] = max(MIN_FONT, el["font_size"] * s)


def _fill_bgs(bgs, tw, th):
    for el in bgs:
        el["x"], el["y"] = 0.0, 0.0
        el["width"], el["height"] = tw, th


def _promote_background(bgs, units):
    if bgs:
        return
    candidates = [
        unit for unit in units
        if len(unit["members"]) == 1 and unit["members"][0]["type"] == "image"
    ]
    if not candidates:
        return

    background = max(candidates, key=lambda unit: unit["w"] * unit["h"])
    units.remove(background)
    element = background["members"][0]
    element["fit"] = "cover"
    other_z = [
        member.get("z_index", 0)
        for unit in units
        for member in unit["members"]
    ]
    element["z_index"] = min(other_z, default=element.get("z_index", 0)) - 1
    bgs.append(element)


def _is_bg(el, cw, ch):
    return (
        el["type"] == "image"
        and el["width"] >= 0.85 * cw
        and el["height"] >= 0.85 * ch
        and el["x"] <= 0.08 * cw
        and el["y"] <= 0.08 * ch
    )


def _looks_like_image(unit):
    return any(m["type"] == "image" for m in unit["members"])


def _is_logo(unit):
    return any(
        "logo" in str(member.get("id", "")).lower()
        or "logo" in str(member.get("asset_id", "")).lower()
        for member in unit["members"]
    )


def _clamp(el, tw, th):
    el["width"] = max(0.0, min(float(el["width"]), tw))
    el["height"] = max(0.0, min(float(el["height"]), th))
    el["x"] = max(0.0, min(float(el["x"]), tw - el["width"]))
    el["y"] = max(0.0, min(float(el["y"]), th - el["height"]))
