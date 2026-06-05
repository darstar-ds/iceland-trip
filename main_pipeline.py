import os, json, sys
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Confirm

DATA_FILE = "trip_data.json"
PROMPT_FILE = "prompt_day_trip_planner.txt"
RESULTS_DIR = "results"
PPTX_OUTPUT = os.path.join(RESULTS_DIR, "Iceland_Trip.pptx")
PDF_OUTPUT = os.path.join(RESULTS_DIR, "Iceland_Trip.pdf")

console = Console()

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _sanitize(text):
    """Remove non-ASCII characters that Windows console may not render."""
    return "".join(c if ord(c) < 128 else "?" for c in str(text))


def _guess_region(lat, lon):
    if lat is None or lon is None:
        return ""
    if lat >= 64.7 and lon <= -21.0:
        return "Snaefellsnes"
    if lon <= -22.0 and lat < 64.3:
        return "Reykjanes"
    if -21.5 <= lon <= -19.5 and 64.0 <= lat <= 64.5:
        return "Golden Circle"
    if lon <= -19.0 and lat < 64.1:
        return "South Coast"
    if -22.5 <= lon <= -21.5 and 64.0 <= lat <= 64.3:
        return "Reykjavik"
    return "Other"


def _fmt_date(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{WEEKDAYS[dt.weekday()]} {dt.day} June"


def _show_summary(data):
    bookings = sorted(
        [loc for loc in data["locations"] if loc.get("is_booking") and loc.get("start_booking")],
        key=lambda x: x["start_booking"]
    )
    attractions = [loc for loc in data["locations"]
                   if loc.get("is_included") and not loc.get("is_booking") and loc.get("type") != "transport"]
    airport = data["trip"]["airport"]

    console.print()
    console.print(Panel("[bold blue]Trip Overview[/]", expand=False))
    trip = data["trip"]
    console.print(f"  Dates:  {_fmt_date(trip['start_date'])} -> {_fmt_date(trip['end_date'])}")
    console.print(f"  Airport: {airport['name']}")
    console.print(f"  Max day hours: {trip.get('max_day_hours', 10)}h  |  Avg speed: {trip.get('avg_speed_kmh', 70)} km/h")
    console.print()

    # ── Bookings table ──────────────────────────────────────────────────
    tbl_b = Table(title=f"[bold]Booked Apartments ({len(bookings)})[/]", title_justify="left")
    tbl_b.add_column("#", style="dim", width=2)
    tbl_b.add_column("Apartment", style="cyan", no_wrap=True)
    tbl_b.add_column("Check-in", style="green")
    tbl_b.add_column("Check-out", style="red")
    tbl_b.add_column("Area", style="yellow")

    for i, b in enumerate(bookings, 1):
        area = _guess_region(b.get("lat"), b.get("lon"))
        tbl_b.add_row(
            str(i),
            b["name"],
            _fmt_date(b["start_booking"]),
            _fmt_date(b.get("end_booking", trip["end_date"])),
            area,
        )
    console.print(tbl_b)
    console.print()

    # ── Attractions table ───────────────────────────────────────────────
    tbl_a = Table(title=f"[bold]Attractions ({len(attractions)})[/]", title_justify="left")
    tbl_a.add_column("#", style="dim", width=2)
    tbl_a.add_column("Name", style="cyan", no_wrap=True)
    tbl_a.add_column("Visit", style="white", justify="right", width=8)
    tbl_a.add_column("Region", style="yellow")
    tbl_a.add_column("Description", style="dim", max_width=50, no_wrap=False)

    for i, a in enumerate(attractions, 1):
        v = a.get("est_visit_time", 0.5)
        visit = f"{int(v * 60)}min" if v < 0.75 else f"{int(v)}h{int(round((v - int(v)) * 60))}min" if v % 1 > 0.01 else f"{int(v)}h"
        region = _guess_region(a.get("lat"), a.get("lon"))
        desc = _sanitize(a.get("desc", "")[:80] + ("..." if len(a.get("desc", "")) > 80 else ""))
        name_safe = _sanitize(a["name"])
        tbl_a.add_row(str(i), name_safe, visit, region, desc)

    console.print(tbl_a)
    console.print()


def _load_data():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _convert_pdf_to_images(pdf_path, output_dir):
    try:
        import fitz
    except ImportError:
        console.print("[yellow]  [!]   PyMuPDF not installed — skipping PDF to PNG conversion[/]")
        return []

    doc = fitz.open(pdf_path)
    images = []
    for i, page in enumerate(doc):
        pix = page.get_pixmap(dpi=200)
        img_path = os.path.join(output_dir, f"slide_{i + 1:02d}.png")
        pix.save(img_path)
        images.append(img_path)
        console.print(f"  [OK]   Saved {img_path}")
    doc.close()
    return images


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)

    # ── 1. Load data ────────────────────────────────────────────────────
    data = _load_data()
    _show_summary(data)

    # ── 2. User confirmation ────────────────────────────────────────────
    if not Confirm.ask("\n[bold]Proceed with LLM-powered day planning?[/]"):
        console.print("[yellow]Aborted by user.[/]")
        return

    # ── 3. Agentic LLM planning (multi-turn) ─────────────────────────────
    console.print("\n[bold]Starting agentic trip planner (LLM can ask questions)...[/]")
    sys.path.append(r"C:\Users\dariu\Python_Scripts\AI_Devs4\_tools")

    from agentic_planner import plan_trip_with_agent

    try:
        days = plan_trip_with_agent(data, PROMPT_FILE)
    except RuntimeError as e:
        console.print(f"[red]LLM planning failed: {e}[/]")
        console.print("[yellow]Falling back to heuristic planner...[/]")
        from heuristic_day_planner import plan_days
        days = plan_days(data)

    console.print(f"[green]  [OK]   Planned {len(days)} days[/]")
    for d in days:
        console.print(f"        {d['title']}")

    # ── 4. Build PPTX ───────────────────────────────────────────────────
    console.print("\n[bold]Building PowerPoint presentation...[/]")
    from pptx_builder import build_presentation, IMAGE_GAP_REPORT, print_image_gap_report

    IMAGE_GAP_REPORT.clear()
    build_presentation(days, PPTX_OUTPUT)
    print_image_gap_report()

    # ── 5. Build PDF ────────────────────────────────────────────────────
    console.print("\n[bold]Building PDF...[/]")
    from pdf_builder import build_pdf

    build_pdf(days, PDF_OUTPUT)

    # ── 6. Convert PDF → PNGs ──────────────────────────────────────────
    console.print("\n[bold]Converting PDF to slide images...[/]")
    _convert_pdf_to_images(PDF_OUTPUT, RESULTS_DIR)

    # ── 7. Summary ──────────────────────────────────────────────────────
    console.print()
    console.print(Panel(f"[bold green]All outputs saved to '{RESULTS_DIR}/'[/]"))
    console.print(f"  * {PPTX_OUTPUT}")
    console.print(f"  * {PDF_OUTPUT}")
    for f in sorted(os.listdir(RESULTS_DIR)):
        if f.startswith("slide_") and f.endswith(".png"):
            console.print(f"  * {os.path.join(RESULTS_DIR, f)}")
    console.print()


if __name__ == "__main__":
    main()
