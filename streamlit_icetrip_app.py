import streamlit as st
import json
import os
from datetime import datetime

st.set_page_config(page_title="Iceland Trip Planner", layout="wide")
st.title("Iceland Trip Planner")

DATA_FILE = "trip_data.json"
RESULTS_DIR = "results"
PROMPT_FILE = "prompt_day_trip_planner.txt"
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

os.makedirs(RESULTS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "data" not in st.session_state:
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        st.session_state.data = json.load(f)
if "plan_result" not in st.session_state:
    st.session_state.plan_result = None
if "plan_method" not in st.session_state:
    st.session_state.plan_method = "Heuristic"
if "generated_pptx" not in st.session_state:
    st.session_state.generated_pptx = None
if "generated_pdf" not in st.session_state:
    st.session_state.generated_pdf = None
if "image_map" not in st.session_state:
    st.session_state.image_map = {}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _editable_attractions(data):
    return [
        loc for loc in data["locations"]
        if not loc.get("is_booking") and loc.get("type") != "transport"
    ]


def _bookings(data):
    return sorted(
        [loc for loc in data["locations"] if loc.get("is_booking") and loc.get("start_booking")],
        key=lambda x: x["start_booking"],
    )


def _selected_attractions(data):
    return [loc for loc in data["locations"]
            if loc.get("is_included") and not loc.get("is_booking") and loc.get("type") != "transport"]


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


def _fmt_visit(hours):
    if hours < 0.75:
        return f"{int(hours * 60)}min"
    h = int(hours)
    m = int(round((hours - h) * 60))
    return f"{h}h{m}min" if m else f"{h}h"


def _cached_image(name):
    from pptx_builder import _find_cached_image
    return _find_cached_image(name)


def _bulk_fetch_images(locations):
    from pptx_builder import fetch_all_images
    result = fetch_all_images(locations)
    st.session_state.image_map.update(result)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

st.sidebar.header("Navigation")
page = st.sidebar.radio(
    "Go to",
    ["Edit Attractions", "Trip Overview", "Generate Plan", "Results", "About / Help"],
    label_visibility="collapsed",
)
st.sidebar.divider()
st.sidebar.caption(f"Locations: {len(st.session_state.data['locations'])}")

# ===================================================================
# STEP 1 — EDIT ATTRACTIONS
# ===================================================================

if page == "Edit Attractions":
    st.header("1. Edit Attractions")
    st.markdown("Toggle which attractions are included and adjust estimated visit times.")

    editable = _editable_attractions(st.session_state.data)
    if not editable:
        st.info("No editable attractions found.")
    else:
        st.subheader(f"Attractions ({len(editable)})")

        # ── Fetch images ──────────────────────────────────────────────
        cached_count = sum(1 for loc in editable if _cached_image(loc["name"]))
        if cached_count < len(editable):
            if st.button(f"📷 Fetch images ({cached_count}/{len(editable)} cached)", width="stretch"):
                _bulk_fetch_images(st.session_state.data["locations"])
                st.rerun()
        else:
            st.caption(f"✅ All {len(editable)} images cached locally.")

        # ── Header ────────────────────────────────────────────────────
        header_cols = st.columns([1, 3.5, 1.2, 0.9, 1])
        header_cols[0].markdown("**Photo**")
        header_cols[1].markdown("**Name**")
        header_cols[2].markdown("**Region**")
        header_cols[3].markdown("**Include**")
        header_cols[4].markdown("**Hours**")
        st.divider()

        # ── Rows ──────────────────────────────────────────────────────
        for i, loc in enumerate(editable):
            cols = st.columns([1, 3.5, 1.2, 0.9, 1])

            img_path = _cached_image(loc["name"])
            if img_path:
                cols[0].image(img_path, width=125)
            else:
                cols[0].markdown("📍")

            desc = (loc.get("desc", "") or "")[:80]
            cols[1].markdown(f"**{loc['name']}**  \n{desc}" if desc else f"**{loc['name']}**")

            cols[2].markdown(_guess_region(loc.get("lat"), loc.get("lon")))

            included_key = f"inc_{i}"
            included = cols[3].checkbox(
                "",
                key=included_key,
                value=loc.get("is_included", True),
                label_visibility="collapsed",
            )

            visit_key = f"time_{i}"
            visit = cols[4].number_input(
                "",
                key=visit_key,
                value=loc.get("est_visit_time", 1.0),
                step=0.25,
                min_value=0.1,
                format="%.2f",
                label_visibility="collapsed",
            )

            st.divider()

        # ── Apply ─────────────────────────────────────────────────────
        if st.button("Apply Changes", type="primary", width="stretch"):
            for i, loc in enumerate(editable):
                loc["is_included"] = st.session_state.get(f"inc_{i}", loc.get("is_included", True))
                loc["est_visit_time"] = st.session_state.get(f"time_{i}", loc.get("est_visit_time", 1.0))
            n_selected = sum(
                1 for loc in st.session_state.data["locations"]
                if loc.get("is_included") and not loc.get("is_booking") and loc.get("type") != "transport"
            )
            st.success(f"Changes applied — {n_selected} attractions selected.")
            st.session_state.generated_pptx = None
            st.session_state.generated_pdf = None

    # ── Add new attraction ──────────────────────────────────────────────
    st.divider()
    with st.expander("Add New Attraction"):
        with st.form("add_attraction_form"):
            col1, col2 = st.columns(2)
            new_name = col1.text_input("Name *")
            new_lat = col2.number_input("Latitude *", value=64.0, format="%.6f")
            col3, col4 = st.columns(2)
            new_lon = col3.number_input("Longitude *", value=-19.0, format="%.6f")
            new_visit = col4.number_input("Est. visit time (hours)", value=1.0, step=0.25, min_value=0.1)
            new_desc = st.text_area("Description")
            new_wiki = st.text_input("Wikipedia page name (optional)")
            submitted = st.form_submit_button("Add to Trip", type="primary", width="stretch")
            if submitted:
                errors = []
                if not new_name:
                    errors.append("Name is required")
                if new_lat == 0.0 and new_lon == 0.0:
                    errors.append("Latitude and Longitude appear to be zero — double-check")
                if errors:
                    for e in errors:
                        st.error(e)
                else:
                    new_loc = {
                        "name": new_name,
                        "type": "attraction",
                        "is_included": True,
                        "is_booking": False,
                        "start_booking": None,
                        "end_booking": None,
                        "est_visit_time": new_visit,
                        "lat": new_lat,
                        "lon": new_lon,
                        "wiki": new_wiki if new_wiki else None,
                        "desc": new_desc,
                    }
                    st.session_state.data["locations"].append(new_loc)
                    st.session_state.image_map.pop(new_name, None)
                    st.success(f"Added '{new_name}'!")
                    st.rerun()

# ===================================================================
# STEP 2 — TRIP OVERVIEW
# ===================================================================

elif page == "Trip Overview":
    st.header("2. Trip Overview")

    data = st.session_state.data
    trip = data["trip"]
    airport = trip["airport"]
    bookings = _bookings(data)
    attractions = _selected_attractions(data)

    col1, col2, col3 = st.columns(3)
    col1.metric("Start", _fmt_date(trip["start_date"]))
    col2.metric("End", _fmt_date(trip["end_date"]))
    col3.metric("Airport", airport["name"])

    col1.metric("Max day hours", f'{trip.get("max_day_hours", 10)}h')
    col2.metric("Avg speed", f'{trip.get("avg_speed_kmh", 70)} km/h')
    col3.metric("Attractions selected", len(attractions))

    # ── Bookings ────────────────────────────────────────────────────────
    if bookings:
        st.subheader(f"Bookings ({len(bookings)})")
        b_rows = []
        for i, b in enumerate(bookings, 1):
            b_rows.append({
                "#": i,
                "Apartment": b["name"],
                "Check-in": _fmt_date(b["start_booking"]),
                "Check-out": _fmt_date(b.get("end_booking", trip["end_date"])),
                "Area": _guess_region(b.get("lat"), b.get("lon")),
            })
        st.dataframe(b_rows, hide_index=True, width="stretch")

    # ── Attractions ─────────────────────────────────────────────────────
    if attractions:
        st.subheader(f"Selected Attractions ({len(attractions)})")
        a_rows = []
        for i, a in enumerate(attractions, 1):
            v = a.get("est_visit_time", 0.5)
            a_rows.append({
                "#": i,
                "Name": a["name"],
                "Visit": _fmt_visit(v),
                "Region": _guess_region(a.get("lat"), a.get("lon")),
                "Description": (a.get("desc", "") or "")[:80],
            })
        st.dataframe(a_rows, hide_index=True, width="stretch")

    if not attractions:
        st.warning("No attractions selected. Go back to Step 1 and toggle some on.")

# ===================================================================
# STEP 3 — GENERATE PLAN
# ===================================================================

elif page == "Generate Plan":
    st.header("3. Generate Plan")

    data = st.session_state.data
    attractions = _selected_attractions(data)
    if not attractions:
        st.warning("No attractions selected. Go to Step 1 and enable at least one.")
        st.stop()

    st.subheader("Planner Method")
    method = st.radio(
        "Choose a planner:",
        ["Heuristic (fast, deterministic)", "Simple LLM (uses AI)"],
        horizontal=True,
        label_visibility="collapsed",
    )
    st.session_state.plan_method = "LLM" if "LLM" in method else "Heuristic"

    if st.session_state.plan_method == "LLM":
        st.info(
            "The LLM planner calls OpenRouter AI to generate an optimised day-by-day itinerary. "
            "This takes 10–30 seconds."
        )
    else:
        st.info(
            "The heuristic planner assigns attractions to available days based on proximity to bookings. "
            "Fast but less flexible."
        )

    if st.button("Generate Plan", type="primary", width="stretch"):
        st.session_state.plan_result = None
        st.session_state.generated_pptx = None
        st.session_state.generated_pdf = None
        os.makedirs(RESULTS_DIR, exist_ok=True)

        if st.session_state.plan_method == "LLM":
            with st.spinner("Calling OpenRouter AI — this may take a minute..."):
                try:
                    from llm_utils import call_llm_for_days
                    days = call_llm_for_days(data, PROMPT_FILE)
                    st.session_state.plan_result = days
                except RuntimeError as e:
                    st.error(f"LLM planning failed: {e}")
                    st.info("Falling back to heuristic planner...")
                    from heuristic_day_planner import plan_days
                    days = plan_days(data)
                    st.session_state.plan_result = days
        else:
            with st.spinner("Running heuristic planner..."):
                from heuristic_day_planner import plan_days
                days = plan_days(data)
                st.session_state.plan_result = days

        if st.session_state.plan_result:
            st.success(f"Plan generated — {len(st.session_state.plan_result)} days — switch to the **Results** tab above")

    if st.session_state.plan_result:
        st.subheader("Preview")
        for d in st.session_state.plan_result:
            locs = d.get("locations", [])
            names = [l["name"] for l in locs if l.get("name")][:4]
            label = f"{d['title']} — {', '.join(names)}{'...' if len(names) < len(locs) else ''}"
            st.caption(label)

# ===================================================================
# STEP 4 — RESULTS
# ===================================================================

elif page == "Results":
    st.header("4. Results")

    if not st.session_state.plan_result:
        st.warning("No plan generated yet. Go to Step 3 and run the planner first.")
        st.stop()

    days = st.session_state.plan_result
    st.success(f"Trip planned — {len(days)} days")

    for i, day in enumerate(days):
        with st.expander(f"{day['title']}", expanded=(i < 2)):
            locs = day.get("locations", [])
            for j, loc in enumerate(locs):
                name = loc.get("name", "?")
                desc = loc.get("desc", "")
                visit = loc.get("est_visit_time")
                icon = "🛏️" if loc.get("is_booking") else "✈️" if loc.get("type") == "transport" else "📍"
                st.markdown(f"{icon} **{name}**" + (f" — {_fmt_visit(visit)}" if visit else ""))
                if desc:
                    st.caption(desc[:200])

    # ── Download buttons ────────────────────────────────────────────────
    st.divider()
    st.subheader("Download Outputs")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Generate PPTX", width="stretch"):
            with st.spinner("Building PowerPoint (this fetches images)..."):
                from pptx_builder import build_presentation, IMAGE_GAP_REPORT, print_image_gap_report
                IMAGE_GAP_REPORT.clear()
                pptx_path = os.path.join(RESULTS_DIR, "Iceland_Trip.pptx")
                build_presentation(days, pptx_path)
                with open(pptx_path, "rb") as f:
                    st.session_state.generated_pptx = f.read()

        if st.session_state.generated_pptx:
            st.download_button(
                "Download PPTX",
                data=st.session_state.generated_pptx,
                file_name="Iceland_Trip.pptx",
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                width="stretch",
            )

    with col2:
        if st.button("Generate PDF", width="stretch"):
            with st.spinner("Building PDF..."):
                from pdf_builder import build_pdf
                pdf_path = os.path.join(RESULTS_DIR, "Iceland_Trip.pdf")
                build_pdf(days, pdf_path)
                with open(pdf_path, "rb") as f:
                    st.session_state.generated_pdf = f.read()

        if st.session_state.generated_pdf:
            st.download_button(
                "Download PDF",
                data=st.session_state.generated_pdf,
                file_name="Iceland_Trip.pdf",
                mime="application/pdf",
                width="stretch",
            )

# ===================================================================
# ABOUT / HELP
# ===================================================================

elif page == "About / Help":
    st.header("About Iceland Trip Planner")

    st.markdown("""
    Plan optimal day-by-day road-trip itineraries for Iceland. Enter your attractions and
    accommodation bookings, and the app generates a multi-day route that respects driving
    times, visit durations, and daily limits.
    """)

    with st.expander("How It Works — Pipeline", expanded=True):
        st.markdown("""
        ```
        trip_data.json  ──►  Edit Attractions  ──►  Planner  ──►  PPTX / PDF
                                │                        │
                            Toggle is_included,         Heuristic or
                            edit visit times,           LLM (OpenRouter AI)
                            add new attractions
        ```
        """)

    with st.expander("Planners"):
        st.markdown("""
        **Heuristic** (fast, no API key needed)
        - Groups attractions by which accommodation they are nearest to.
        - Sorts groups west-to-east for efficient driving.
        - Spreads attractions across the nights spent at each accommodation.
        - Always produces a valid plan, works entirely offline.

        **Simple LLM** (calls OpenRouter AI)
        - Sends trip data as a structured prompt to an LLM.
        - The LLM returns a JSON itinerary respecting all constraints.
        - Validates the response schema and retries up to 2 times on failure.
        - Requires `API_OPENROUTER_KEY` in Streamlit Secrets.
        """)

    with st.expander("Modules"):
        st.markdown("""
        | File | Role |
        |------|------|
        | `streamlit_icetrip_app.py` | This app — 5-step UI |
        | `trip_data.json` | Trip input: dates, bookings, attractions, coordinates |
        | `llm_utils.py` | Prompt builder + LLM caller with retry logic |
        | `heuristic_day_planner.py` | Deterministic fallback planner |
        | `agentic_planner.py` | Multi-turn interactive planner (CLI only) |
        | `openrouter_utils.py` | OpenRouter API wrapper with `st.secrets` support |
        | `pptx_builder.py` | PowerPoint generator with route maps + images |
        | `pdf_builder.py` | Landscape PDF generator |
        | `main_pipeline.py` | Original CLI entry point |
        """)

    with st.expander("Data Format — trip_data.json"):
        st.markdown("""
        ```json
        {
          "trip": {
            "start_date": "2026-06-06",
            "end_date": "2026-06-14",
            "max_day_hours": 10,
            "avg_speed_kmh": 70,
            "airport": { "name": "Keflavik Airport", "lat": 63.985, "lon": -22.605 }
          },
          "locations": [
            {
              "name": "Hallgrimskirkja",
              "type": "attraction",
              "is_included": true,
              "is_booking": false,
              "est_visit_time": 0.5,
              "lat": 64.141795,
              "lon": -21.92671,
              "wiki": "Hallgrímskirkja",
              "desc": "Iceland's iconic 74 m basalt-column church."
            }
          ]
        }
        ```

        - **`type`**: `"attraction"`, `"accommodation"`, or `"transport"`.
        - **`is_booking`**: `true` for accommodations.
        - **`is_included`**: `true` to include in the plan.
        - **`est_visit_time`**: estimated visit duration in hours.
        - **`wiki`**: Wikipedia page title (used for image fetching).
        """)

    with st.expander("Deploy on Streamlit Community Cloud"):
        st.markdown("""
        1. Push the repo to GitHub.
        2. Go to [Streamlit Community Cloud](https://streamlit.io/cloud) → **New app**.
        3. Select the repo and set the main file to `streamlit_icetrip_app.py`.
        4. In **Settings → Secrets**, add:
           ```toml
           API_OPENROUTER_KEY = "sk-or-v1-..."
           ```
           (Get a key at [openrouter.ai/keys](https://openrouter.ai/keys).)
        5. Deploy. The heuristic planner works without any API key.
        """)

    with st.expander("Requirements"):
        st.markdown("""
        - Python 3.10+
        - Dependencies in `requirements.txt`
        - No system packages needed (PDF uses `fpdf2`, not LaTeX)
        """)
