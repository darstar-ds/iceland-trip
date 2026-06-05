"""
Agentic trip planner — multi-turn LLM conversation to resolve scheduling issues.

Replaces the single-shot LLM call with an interactive loop where the LLM can
ask the user yes/no or choice questions, suggest removing attractions, then
iteratively refine the plan until a valid final plan is produced.
"""

import json
import re
import sys
from datetime import datetime

sys.path.append(r"C:\Users\dariu\Python_Scripts\AI_Devs4\_tools")
from openrouter import ask_openrouter
from rich.console import Console
from rich.prompt import Confirm, IntPrompt

DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
MAX_TURNS = 10
REQUIRED_DAY_FIELDS = {"day_number", "date", "label", "locations_in_order"}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

AGENT_PROTOCOL = """\
# Agent Protocol

You are an interactive trip-planning agent. Instead of outputting a plan immediately, you may ask the user ONE question per turn to resolve issues. Only output the final plan when you are confident it fits all constraints.

## Available Actions

1. Ask a yes/no question — when the user can confirm or reject a suggestion.
2. Ask a choice question — when the user should pick from options.
3. Output the final plan — when all issues are resolved.

## Response Format

Respond with a JSON object containing a "type" field.

### To ask a question (one per turn):

{
  "type": "question",
  "id": "a_unique_id_for_dedup",
  "question": "Clear question text for the user...",
  "answer_type": "yes_no",
  "if_yes": { "action": "remove_locations", "locations": ["Exact Name 1", "Exact Name 2"] },
  "if_no": { "action": "booking_change_declined" }
}

For choice questions:
{
  "type": "question",
  "id": "which_to_remove",
  "question": "Which attraction should we drop?",
  "answer_type": "choice",
  "options": [
    { "label": "Name (visit time)", "value": "Exact Name" }
  ],
  "action": "remove_locations"
}

### To acknowledge:
{ "type": "info", "message": "Brief acknowledgment..." }

### To output the final plan:
{
  "type": "plan",
  "trip_title": "...",
  "days": [
    {
      "day_number": 1,
      "date": "2026-06-06",
      "label": "Arrival - Reykjavik",
      "locations_in_order": ["Keflavik Airport", "NORR Apartment, Reykjavik"],
      "estimated_km": 50,
      "estimated_hours": 2.0,
      "notes": "..."
    }
  ]
}

## Rules
- Ask only ONE question per turn.
- Do NOT repeat a question with the same id.
- If the user declined booking changes, do NOT ask about date changes again.
- Prefer suggesting removals of low-value or redundant attractions before asking about booking changes.
- When you output the final plan, it must include ALL remaining attractions — none left out.
- Day 1 is always the arrival day (airport -> first accommodation).
- The final day must return to the airport.
- Valid JSON only — no markdown, no code fences.
"""


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
    mapped = []
    errors = []
    for day in days:
        locs = []
        for name in day["locations_in_order"]:
            if name not in name_to_loc:
                errors.append(f"Day {day['day_number']}: location '{name}' not found")
                continue
            locs.append(name_to_loc[name])
        if not locs:
            errors.append(f"Day {day['day_number']}: no valid locations after mapping")
        date_str = day["date"]
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        day_title = (
            f"Day {day['day_number']} - {WEEKDAYS[dt.weekday()]} {dt.day} June "
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


class AgenticPlanner:
    def __init__(self, trip_data, base_prompt_path, model=DEFAULT_MODEL):
        self.original_data = trip_data
        self.base_prompt_path = base_prompt_path
        self.model = model
        self.excluded_names = set()
        self.booking_changes_declined = False
        self.conversation = []
        self.asked_ids = set()
        self._name_to_loc = None

    @property
    def active_payload(self):
        included = [
            loc for loc in self.original_data.get("locations", [])
            if loc.get("is_included") and loc["name"] not in self.excluded_names
        ]
        return {
            "trip": self.original_data["trip"],
            "locations": included,
        }

    @property
    def name_to_loc(self):
        if self._name_to_loc is None:
            payload = self.active_payload
            mapping = {loc["name"]: loc for loc in payload.get("locations", [])}
            mapping[payload["trip"]["airport"]["name"]] = payload["trip"]["airport"]
            self._name_to_loc = mapping
        return self._name_to_loc

    def _build_prompt(self):
        with open(self.base_prompt_path, "r", encoding="utf-8") as f:
            base = f.read()

        payload = self.active_payload
        max_hours = payload.get("trip", {}).get("max_day_hours", 10)
        avg_speed = payload.get("trip", {}).get("avg_speed_kmh", 70)

        base = base.replace("{{ TRIP_DATA_JSON }}", json.dumps(payload, indent=2, ensure_ascii=False))
        base = base.replace("{max_day_hours}", str(max_hours))
        base = base.replace("{avg_speed_kmh}", str(avg_speed))

        parts = [AGENT_PROTOCOL, "", base]

        if self.conversation:
            parts.append("")
            parts.append("## Conversation History")
            for role, content in self.conversation:
                prefix = "User: " if role == "user" else "Assistant: "
                parts.append(f"{prefix}{content}")

        if self.booking_changes_declined:
            parts.append("")
            parts.append("## Constraint")
            parts.append("The user has declined to change any booking dates. Do NOT ask about date changes.")

        parts.append("")
        parts.append("## Current Turn")
        parts.append("Review the trip data and either ask a question or output the final plan.")

        return "\n".join(parts)

    def _display_question(self, q):
        console = Console()
        console.print()
        console.print("[bold yellow]LLM Question:[/]")

        if q["answer_type"] == "yes_no":
            console.print(f"  {q['question']}")
            return "yes" if Confirm.ask("  Your answer") else "no"

        elif q["answer_type"] == "choice":
            console.print(f"  {q['question']}")
            options = q.get("options", [])
            for i, opt in enumerate(options, 1):
                console.print(f"  [{i}] {opt['label']}")
            choice = IntPrompt.ask("  Select number", default=1)
            if 1 <= choice <= len(options):
                return options[choice - 1]["value"]
            return None

        return None

    def _apply_question_action(self, q, answer):
        if q["answer_type"] == "yes_no":
            if answer == "yes" and q.get("if_yes"):
                action = q["if_yes"]
            elif answer == "no" and q.get("if_no"):
                action = q["if_no"]
            else:
                return
        else:
            act_type = q.get("action")
            if act_type == "remove_locations":
                action = {"action": act_type, "locations": [answer] if answer else []}
            elif act_type:
                action = {"action": act_type}
            else:
                return

        act_type = action.get("action")
        if act_type == "remove_locations":
            for name in action.get("locations", []):
                self.excluded_names.add(name)
            self._name_to_loc = None
        elif act_type == "booking_change_declined":
            self.booking_changes_declined = True

    def plan(self):
        console = Console()

        for turn in range(1, MAX_TURNS + 1):
            console.print(f"\n[dim]--- Agent turn {turn}/{MAX_TURNS} ---[/]")

            prompt = self._build_prompt()
            raw = ask_openrouter(prompt, model=self.model)
            cleaned = _extract_json(raw)

            try:
                response = json.loads(cleaned)
            except json.JSONDecodeError as e:
                console.print(f"[red]  JSON parse error: {e}[/]")
                self.conversation.append(("assistant", raw))
                self.conversation.append(("user",
                    f"Your response was not valid JSON. Error: {e}. Return ONLY valid JSON."))
                continue

            resp_type = response.get("type")

            if resp_type == "question":
                qid = response.get("id", "")
                if qid in self.asked_ids:
                    console.print("[yellow]  Skipping repeated question[/]")
                    self.conversation.append(("assistant", raw))
                    self.conversation.append(("user",
                        "You already asked that question. Ask something different or output the final plan."))
                    continue

                self.asked_ids.add(qid)
                answer = self._display_question(response)
                if answer is None:
                    console.print("[yellow]  Invalid choice, skipping[/]")
                    self.conversation.append(("assistant", raw))
                    self.conversation.append(("user", "Invalid choice. Please try again or output the final plan."))
                    continue

                self._apply_question_action(response, answer)
                self.conversation.append(("assistant", raw))
                self.conversation.append(("user", f"User answered: {answer}"))
                console.print(f"[green]  [OK]   User answered: {answer}[/]")

            elif resp_type == "plan":
                valid, msg = _validate_schema(response)
                if not valid:
                    console.print(f"[red]  Schema error: {msg}[/]")
                    self.conversation.append(("assistant", raw))
                    self.conversation.append(("user",
                        f"Schema error: {msg}. Fix and return valid JSON."))
                    continue

                mapped, map_errors = _map_names_to_locations(response["days"], self.name_to_loc)
                if map_errors:
                    for err in map_errors:
                        console.print(f"[red]  {err}[/]")
                    self.conversation.append(("assistant", raw))
                    self.conversation.append(("user",
                        "Location name mismatches:\n" + "\n".join(map_errors) +
                        "\nUse EXACT names from the trip data."))
                    continue

                console.print(f"[green]  [OK]   Final plan received ({len(mapped)} days)[/]")
                return mapped

            elif resp_type == "info":
                msg = response.get("message", "")
                console.print(f"[dim]  LLM says: {msg}[/]")
                self.conversation.append(("assistant", raw))

            else:
                console.print(f"[red]  Unknown response type: {resp_type}[/]")
                self.conversation.append(("assistant", raw))
                self.conversation.append(("user",
                    f"Unknown type '{resp_type}'. Use 'question', 'plan', or 'info'."))

        raise RuntimeError(f"Agent loop did not produce a plan after {MAX_TURNS} turns.")


def plan_trip_with_agent(trip_data, base_prompt_path, model=DEFAULT_MODEL):
    planner = AgenticPlanner(trip_data, base_prompt_path, model)
    return planner.plan()
