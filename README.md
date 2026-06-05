# Iceland Trip Planner

Plan optimal day-by-day road-trip itineraries for Iceland. The application takes a set of attractions and accommodation bookings and generates a multi-day route that respects driving times, visit durations, and daily limits.

## How It Works

The application is built around a pipeline with several modular components:

### Pipeline

```
trip_data.json  ──►  Data Editor (Streamlit) ──►  Planner ──►  PPTX / PDF
                        │                            │
                    Edit is_included,              Heuristic or LLM
                    est_visit_time,                (OpenRouter AI)
                    add attractions
```

### Modules

| Module | Role |
|--------|------|
| `trip_data.json` | Input file describing the trip: dates, accommodations, attractions with coordinates, descriptions, and metadata. |
| `streamlit_icetrip_app.py` | 4-step Streamlit frontend: edit attractions, review overview, generate plan, download results. |
| `llm_utils.py` | Builds a prompt from trip data and calls OpenRouter AI to produce a JSON itinerary in one shot. Includes retry logic for JSON validation and schema checking. |
| `agentic_planner.py` | An interactive multi-turn planner where the LLM can ask the user yes/no or choice questions to resolve scheduling conflicts before outputting a final plan. Used by the CLI pipeline. |
| `heuristic_day_planner.py` | A deterministic fallback planner that assigns attractions to days based on proximity to each accommodation using Haversine distances. Fast and does not require an API key. |
| `openrouter_utils.py` | Thin wrapper around the OpenRouter API. Loads `API_OPENROUTER_KEY` from `st.secrets` (Streamlit) or `os.environ` (CLI). |
| `pptx_builder.py` | Builds a PowerPoint presentation with one slide per day: route map, location thumbnails fetched from Wikipedia/Commons/Flickr, descriptions. |
| `pdf_builder.py` | Builds a landscape PDF with the same layout as the PPTX slides. |
| `main_pipeline.py` | Original CLI entry point (rich-based, terminal UI). Works fully offline with the heuristic fallback. |

### Planners

**Heuristic planner** (`heuristic_day_planner.py`):
- Groups attractions by which accommodation they are nearest to.
- Sorts each group by longitude (west-to-east for efficient driving).
- Spreads attractions across the nights spent at each accommodation.
- Always produces a valid plan and does not need internet.

**Simple LLM planner** (`llm_utils.py`):
- Sends the trip data as a structured prompt to OpenRouter AI.
- The LLM returns a JSON itinerary respecting all constraints (driving time, visit time, accommodation changes).
- Validates the response schema and retries up to 2 times on failure.
- Requires an `API_OPENROUTER_KEY`.

**Agentic planner** (`agentic_planner.py`):
- Multi-turn conversation: the LLM can ask questions (remove an attraction? change bookings?) before finalising.
- Used by the CLI pipeline; not available in the Streamlit app.

## Usage

### Streamlit App (Recommended)

```bash
pip install -r requirements.txt
streamlit run streamlit_icetrip_app.py
```

**Steps:**
1. **Edit Attractions** — toggle `is_included` checkboxes, adjust `est_visit_time` (hours), or add new attractions via the form.
2. **Trip Overview** — review the selected data before planning.
3. **Generate Plan** — choose **Heuristic** (fast, no API key) or **Simple LLM** (calls OpenRouter AI).
4. **Results** — expand each day to see the route, then download PPTX or PDF.

### CLI Pipeline

```bash
python main_pipeline.py
```

Loads `trip_data.json`, shows a summary, then runs the agentic LLM planner (falls back to heuristic if unavailable).

## Data Format

`trip_data.json` structure:

```json
{
  "trip": {
    "start_date": "2026-06-06",
    "end_date": "2026-06-14",
    "max_day_hours": 10,
    "avg_speed_kmh": 70,
    "airport": {
      "name": "Keflavik Airport",
      "lat": 63.985,
      "lon": -22.605
    }
  },
  "locations": [
    {
      "name": "Hallgrimskirkja",
      "type": "attraction",
      "is_included": true,
      "is_booking": false,
      "start_booking": null,
      "end_booking": null,
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
- **`is_booking`**: `true` for accommodations (hotels, apartments, etc.).
- **`is_included`**: `true` to include in the plan.
- **`est_visit_time`**: estimated visit duration in hours.
- **`wiki`**: Wikipedia page title (used for image fetching).
- **`day`** / **`domain`** (optional): hints for the heuristic planner.

## Deployment on Streamlit Community Cloud

1. Push the repository to GitHub.
2. Go to [Streamlit Community Cloud](https://streamlit.io/cloud) → **New app** → select the repo and set the main file to `streamlit_icetrip_app.py`.
3. In the app dashboard → **Settings → Secrets**, add:
   ```toml
   API_OPENROUTER_KEY = "sk-or-v1-..."
   ```
   (Get a key at [openrouter.ai/keys](https://openrouter.ai/keys).)
4. **Optional** — for interactive Google Maps route previews in the Results page, also add:
   ```toml
   GOOGLE_MAPS_API_KEY = "AIzaSy..."
   ```
   Get a free key at [console.cloud.google.com](https://console.cloud.google.com/apis/credentials) and enable the **Maps Embed API**.
5. Deploy. The heuristic planner and static maps work without any API key.

## Requirements

- Python 3.10+
- See `requirements.txt` for dependencies.
- No system packages are required (PDF generation uses `fpdf2`, not LaTeX or wkhtmltopdf).
