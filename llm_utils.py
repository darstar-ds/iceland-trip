import json, re, os

from openrouter_utils import ask_openrouter

DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
MAX_RETRIES = 2
REQUIRED_DAY_FIELDS = {"day_number", "date", "label", "locations_in_order"}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _format_date(date_str):
    from datetime import datetime
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{WEEKDAYS[dt.weekday()]} {dt.day} June"


def _build_prompt(trip_data, prompt_path):
    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()

    data_json = json.dumps(trip_data, indent=2, ensure_ascii=False)
    max_hours = trip_data.get("trip", {}).get("max_day_hours", 10)
    avg_speed = trip_data.get("trip", {}).get("avg_speed_kmh", 70)

    prompt = template.replace("{{ TRIP_DATA_JSON }}", data_json)
    prompt = prompt.replace("{max_day_hours}", str(max_hours))
    prompt = prompt.replace("{avg_speed_kmh}", str(avg_speed))

    FEEDBACK_FILE = "user_feedback.txt"
    if os.path.exists(FEEDBACK_FILE):
        with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
            feedback = f.read().strip()
        if feedback:
            prompt += "\n\n## User Feedback from Previous Runs\n" + feedback

    return prompt


def _extract_json(text):
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if json_match:
        return json_match.group(1).strip()
    return text.strip()


def _validate_schema(response):
    if "days" not in response or not isinstance(response["days"], list):
        return False, "Missing 'days' array in response"
    if not response["days"]:
        return False, "Empty days array"
    for i, day in enumerate(response["days"]):
        missing = REQUIRED_DAY_FIELDS - set(day.keys())
        if missing:
            return False, f"Day {i+1}: missing fields: {', '.join(sorted(missing))}"
        if not isinstance(day.get("locations_in_order"), list):
            return False, f"Day {i+1}: 'locations_in_order' must be a list"
        if not day.get("locations_in_order"):
            return False, f"Day {i+1}: 'locations_in_order' is empty"
    return True, ""


def _map_names_to_locations(days, name_to_loc):
    """Map location name strings to full location dicts. Returns (mapped_days, errors)."""
    mapped = []
    errors = []
    for day in days:
        locs = []
        for name in day["locations_in_order"]:
            if name not in name_to_loc:
                errors.append(f"Day {day['day_number']}: location '{name}' not found in trip data")
                continue
            locs.append(name_to_loc[name])
        if not locs:
            errors.append(f"Day {day['day_number']}: no valid locations after mapping")
        date_str = day["date"]
        day_title = (
            f"Day {day['day_number']} - {_format_date(date_str)} "
            f"({day.get('estimated_km', '?')} km"
        )
        est_h = day.get("estimated_hours")
        if est_h:
            day_title += f", {est_h}h"
        day_title += f") - {day['label']}"
        mapped.append({
            "title": day_title,
            "locations": locs,
            "date": date_str,
        })
    return mapped, errors


def call_llm_for_days(trip_data, prompt_path, model=DEFAULT_MODEL):
    filtered = _build_filtered_payload(trip_data)
    prompt = _build_prompt(filtered, prompt_path)

    name_to_loc = {loc["name"]: loc for loc in filtered.get("locations", [])}
    name_to_loc[filtered["trip"]["airport"]["name"]] = filtered["trip"]["airport"]

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        raw = ask_openrouter(prompt, model=model)
        cleaned = _extract_json(raw)
        try:
            response = json.loads(cleaned)
        except json.JSONDecodeError as e:
            last_error = f"JSON decode error: {e}"
            if attempt < MAX_RETRIES:
                prompt = (
                    f"Your previous response was not valid JSON.\n"
                    f"Error: {e}\n\n"
                    f"Return ONLY valid JSON matching this template — no markdown, no explanation:\n\n"
                    f'The expected structure is:\n'
                    f'{{"trip_title": "...", "days": [{{"day_number": 1, "date": "YYYY-MM-DD", "label": "...", "locations_in_order": ["Name1", "Name2"], "estimated_km": 0, "estimated_hours": 0.0, "notes": "..."}}]}}\n\n'
                    f'Here is the trip data again:\n\n{json.dumps(filtered, indent=2, ensure_ascii=False)}'
                )
            continue

        valid, msg = _validate_schema(response)
        if valid:
            mapped, map_errors = _map_names_to_locations(response["days"], name_to_loc)
            if map_errors:
                last_error = "; ".join(map_errors)
                if attempt < MAX_RETRIES:
                    prompt = (
                        f"Your previous response had location name mismatches:\n"
                        f"{chr(10).join(map_errors)}\n\n"
                        f'Use EXACT "name" values from this data:\n'
                        f'{json.dumps(filtered, indent=2, ensure_ascii=False)}\n\n'
                        f"Return ONLY valid JSON matching the template."
                    )
                continue
            return mapped

        last_error = msg
        if attempt < MAX_RETRIES:
            prompt = (
                f"Your previous response had a schema error: {msg}\n\n"
                f"Return ONLY valid JSON matching this template:\n\n"
                f'{{"trip_title": "...", "days": [{{"day_number": 1, "date": "YYYY-MM-DD", "label": "...", "locations_in_order": ["Name1", "Name2"], "estimated_km": 0, "estimated_hours": 0.0, "notes": "..."}}]}}\n\n'
                f'Here is the trip data:\n\n{json.dumps(filtered, indent=2, ensure_ascii=False)}'
            )

    raise RuntimeError(f"LLM communication failed after {MAX_RETRIES + 1} attempts. Last error: {last_error}")


def _build_filtered_payload(trip_data):
    included = [loc for loc in trip_data.get("locations", []) if loc.get("is_included")]
    return {
        "trip": trip_data["trip"],
        "locations": included,
    }
