import os
from fpdf import FPDF
from pptx_builder import _ascii_fold, make_map, MAP_DIR, IMG_DIR


def _safe(text):
    """Replace non-Latin-1 characters with ASCII equivalents for the PDF."""
    text = _ascii_fold(str(text))
    replacements = {
        '\u2014': '-', '\u2013': '-',
        '\u2018': "'", '\u2019': "'",
        '\u201c': '"', '\u201d': '"',
        '\u2026': '...',
        '\u2192': '->',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.encode("latin-1", "replace").decode("latin-1")


def build_pdf(days, output_path):
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    pdf = FPDF(orientation="L", format="A4")
    pdf.set_auto_page_break(auto=False)

    for i, day in enumerate(days):
        pdf.add_page()
        _draw_day_page(pdf, i, day)

    pdf.output(output_path)
    print(f"  [OK]   Saved {output_path}")


def _draw_day_page(pdf, day_idx, day):
    page_w = 297
    page_h = 210
    margin = 8
    content_w = page_w - 2 * margin

    # ── Title bar ──────────────────────────────────────────────────────
    pdf.set_fill_color(31, 59, 115)
    pdf.rect(0, 0, page_w, 14, "F")

    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 12)
    title = _safe(day.get("title", f"Day {day_idx + 1}"))
    pdf.set_xy(margin, 3)
    pdf.cell(content_w, 8, title, ln=True)

    # ── Map (right half) ───────────────────────────────────────────────
    map_path = os.path.join(MAP_DIR, f"map_{day_idx}.png")
    if not os.path.exists(map_path):
        try:
            map_path = make_map(day_idx, day.get("locations", []))
        except Exception:
            map_path = None

    map_x = page_w // 2 + 4
    map_y = 18
    map_w = page_w // 2 - margin - 4
    map_h = 130

    if map_path and os.path.exists(map_path):
        pdf.image(map_path, x=map_x, y=map_y, w=map_w, h=map_h)

    # ── Google Maps link ─────────────────────────────────────────────
    pdf.set_xy(map_x, map_y + map_h + 2)
    pdf.set_text_color(0, 102, 204)
    pdf.set_font("Helvetica", "U", 7)
    pdf.cell(map_w, 4, "Open route in Google Maps", ln=True)

    # ── Location list (left half) ─────────────────────────────────────
    locs = day.get("locations", [])
    list_x = margin
    list_y = 18
    list_w = page_w // 2 - margin - 4

    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_xy(list_x, list_y)
    pdf.cell(list_w, 5, f"Stops ({len(locs)})", ln=True)
    list_y += 7

    thumbnail_size = 8

    for loc in locs:
        name = _safe(loc.get("name", ""))
        desc = _safe(loc.get("desc", ""))
        visit = loc.get("est_visit_time")

        if list_y > 170:
            break

        # ── Thumbnail ──────────────────────────────────────────────
        img_path = _find_best_thumb(name)
        thumb_x = list_x
        thumb_y = list_y

        if img_path and os.path.exists(img_path):
            try:
                pdf.image(img_path, x=thumb_x, y=thumb_y, w=thumbnail_size, h=thumbnail_size)
            except Exception:
                pass

        text_x = list_x + thumbnail_size + 2
        text_w = list_w - thumbnail_size - 2

        # ── Name + visit time ──────────────────────────────────────
        pdf.set_xy(text_x, list_y)
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(31, 59, 115)

        label = name
        if visit:
            if visit < 0.75:
                label += f"  -  {int(visit * 60)}min"
            else:
                h = int(visit)
                m = int(round((visit - h) * 60))
                label += f"  -  {h}h{m}min" if m else f"  -  {h}h"
        pdf.cell(text_w, 4, label, ln=True)
        list_y += 4

        # ── Description ────────────────────────────────────────────
        if desc:
            pdf.set_xy(text_x, list_y)
            pdf.set_font("Helvetica", "", 7)
            pdf.set_text_color(60, 60, 60)
            lines = _wrap_text(desc, text_w, pdf, 7)
            for line in lines[:2]:
                if list_y > 170:
                    break
                pdf.set_xy(text_x, list_y)
                pdf.cell(text_w, 3, line, ln=True)
                list_y += 3

        list_y += 2


def _find_best_thumb(name):
    folded = _ascii_fold(name.replace(" ", "_").replace("/", "_"))
    folded = "".join(c for c in folded if c.isalnum() or c in "._()-")
    if not os.path.isdir(IMG_DIR):
        return None

    best = None
    best_prio = 99
    for f in os.listdir(IMG_DIR):
        f_noext, _ = os.path.splitext(f)
        f_folded = _ascii_fold(f_noext).lower()
        if folded.lower() in f_folded:
            prio = 0
            if "_flickr" in f_noext:
                prio = 3
            elif "_geo" in f_noext:
                prio = 4
            elif "_commons" in f_noext:
                prio = 2
            else:
                prio = 1
            if prio < best_prio:
                best_prio = prio
                best = os.path.join(IMG_DIR, f)
    return best


def _wrap_text(text, max_w, pdf, font_size):
    pdf.set_font("Helvetica", "", font_size)
    words = text.split()
    lines = []
    current = ""
    for w in words:
        test = (current + " " + w).strip()
        if pdf.get_string_width(test) > max_w and current:
            lines.append(current)
            current = w
        else:
            current = test
    if current:
        lines.append(current)
    return lines if lines else [text]
