import os, json, math
from datetime import datetime, timedelta
from pptx_builder import (
    build_presentation, fetch_all_images, print_image_gap_report,
    IMAGE_GAP_REPORT, IMG_DIR, MAP_DIR, SCRIPT_DIR
)

DATA_FILE = "trip_data.json"
OUTPUT_FILE = "Iceland_Trip.pptx"

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _route_distance(locs):
    dist = 0
    for i in range(1, len(locs)):
        if locs[i].get("lat") and locs[i - 1].get("lat"):
            dist += haversine(locs[i - 1]["lat"], locs[i - 1]["lon"],
                              locs[i]["lat"], locs[i]["lon"])
    return dist


def _format_date(date_str):
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{WEEKDAYS[dt.weekday()]} {dt.day} June"


def plan_days(data):
    trip = data["trip"]
    locations = [loc for loc in data["locations"] if loc.get("is_included")]

    airport = trip["airport"]
    max_hours = trip.get("max_day_hours", 10)
    avg_speed = trip.get("avg_speed_kmh", 70)

    bookings = sorted(
        [loc for loc in locations if loc.get("is_booking") and loc.get("start_booking")],
        key=lambda x: x["start_booking"]
    )
    attractions = [loc for loc in locations
                   if not loc.get("is_booking") and loc.get("type") != "transport"]

    periods = []
    for i, b in enumerate(bookings):
        end_date = bookings[i + 1]["start_booking"] if i + 1 < len(bookings) else trip["end_date"]
        periods.append({
            "base": b,
            "date_start": b["start_booking"],
            "date_end": end_date,
        })

    for sight in attractions:
        lat, lon = sight["lat"], sight["lon"]
        domain = sight.get("domain")
        if domain is None:
            if lat >= 64.5 and len(periods) > 1:
                domain = 1
            elif lon > -20.0 and lat < 64.5 and len(periods) > 2:
                domain = 2
            else:
                domain = 0
        best_period = periods[min(domain, len(periods) - 1)]
        best_period.setdefault("sights", []).append(sight)

    for p in periods:
        if "sights" not in p:
            p["sights"] = []
        p["sights"].sort(key=lambda s: haversine(s["lat"], s["lon"],
                                                  p["base"]["lat"], p["base"]["lon"]))

    days_out = []
    day_idx = 1

    day_title = f"Day {day_idx} - {_format_date(trip['start_date'])} - Arrival"
    days_out.append({
        "title": day_title,
        "locations": [airport, bookings[0]] if bookings else [airport],
        "date": trip["start_date"],
    })
    day_idx += 1

    for period_idx, p in enumerate(periods):
        p_start = datetime.strptime(p["date_start"], "%Y-%m-%d")
        p_end = datetime.strptime(p["date_end"], "%Y-%m-%d")
        num_days = (p_end - p_start).days

        sights = list(p["sights"])
        if not sights:
            continue

        start_offset = 1 if p == periods[0] else 0
        available_slots = num_days - start_offset
        if available_slots <= 0:
            continue

        sorted_sights = sorted(sights, key=lambda s: -s["lon"])
        n_slots = min(len(sorted_sights), available_slots)
        groups = []
        for i in range(n_slots):
            start = i * len(sorted_sights) // n_slots
            end = (i + 1) * len(sorted_sights) // n_slots
            groups.append(sorted_sights[start:end])

        for s in sights:
            d = s.get("day")
            if d is not None and 0 <= d < n_slots:
                for g in groups:
                    if s in g and g is not groups[d]:
                        g.remove(s)
                        groups[d].append(s)
                        break

        for j, group in enumerate(groups):
            date = p_start + timedelta(days=start_offset + j)
            date_str = date.strftime("%Y-%m-%d")

            if period_idx > 0 and j == 0:
                start_base = periods[period_idx - 1]["base"]
                end_base = p["base"]
            else:
                start_base = p["base"]
                end_base = p["base"]

            ordered = [min(group, key=lambda s: haversine(start_base["lat"], start_base["lon"], s["lat"], s["lon"]))]
            remaining = [s for s in group if s is not ordered[0]]
            while remaining:
                last = ordered[-1]
                best = min(remaining, key=lambda s: haversine(last["lat"], last["lon"], s["lat"], s["lon"]))
                ordered.append(best)
                remaining.remove(best)

            route = [start_base] + ordered + [end_base]
            route_km = int(_route_distance(route))
            total_time = sum(loc.get("est_visit_time", 0.5) for loc in group) + route_km / avg_speed
            day_title = f"Day {day_idx} - {_format_date(date_str)} ({route_km} km, {total_time:.1f}h)"

            days_out.append({
                "title": day_title,
                "locations": route,
                "date": date_str,
            })
            day_idx += 1

    last_date = days_out[-1].get("date", "")
    if last_date != trip["end_date"]:
        last_accommodation = bookings[-1] if bookings else airport
        route = [last_accommodation, airport]
        route_km = int(_route_distance(route))
        day_title = f"Day {day_idx} - {_format_date(trip['end_date'])} ({route_km} km) - Return to Airport"
        days_out.append({
            "title": day_title,
            "locations": route,
            "date": trip["end_date"],
        })
    else:
        last = days_out[-1]
        if airport not in last["locations"]:
            last["locations"].append(airport)
        last["title"] = last["title"].replace(" (", " \u2192 Airport (")

    return days_out


def main():
    IMAGE_GAP_REPORT.clear()

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    days = plan_days(data)

    print(f"\nPlanned {len(days)} days from {len(data['locations'])} locations\n")

    build_presentation(days, OUTPUT_FILE)

    print_image_gap_report()


if __name__ == "__main__":
    main()
