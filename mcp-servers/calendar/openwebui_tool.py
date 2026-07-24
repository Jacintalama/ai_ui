"""
title: Calendar
author: AIUI Team
version: 0.1.0
description: Google Calendar in chat. See your schedule, create events and meetings (with Google Meet), update or cancel them. Connecting is a one-click inline button. Per-user: each person uses their own calendar.
"""

# Native Open WebUI tool. The model calls these directly; OWUI injects the
# signed-in user via __user__ so every action is per-user. On "not connected"
# the calendar server returns a message containing the /calendar/auth/google/start
# URL, which the frontend (integrations-ui.js) turns into an inline Connect button.

import httpx
from pydantic import BaseModel, Field
from typing import List, Optional


class Tools:
    class Valves(BaseModel):
        calendar_url: str = Field(default="http://mcp-calendar:8000")
        default_timezone: str = Field(default="Asia/Manila")
        timeout_seconds: int = Field(default=30)

    def __init__(self):
        self.valves = self.Valves()

    def _email(self, __user__: dict) -> str:
        return (__user__ or {}).get("email", "default@local")

    async def _post(self, path: str, payload: dict, user_email: str) -> dict:
        async with httpx.AsyncClient(timeout=self.valves.timeout_seconds) as client:
            r = await client.post(
                f"{self.valves.calendar_url}/{path}",
                json=payload,
                headers={"X-User-Email": user_email},
            )
            try:
                return r.json()
            except Exception:
                return {"error": f"Calendar returned an unexpected response ({r.status_code})."}

    async def list_calendar_events(
        self, time_min: str = None, time_max: str = None,
        max_results: int = 25, __user__: dict = {},
    ) -> str:
        """
        List upcoming Google Calendar events (defaults to the next 7 days). Use
        when the user asks about their schedule, agenda, or what's coming up.

        :param time_min: Optional start of range in ISO 8601 (defaults to now).
        :param time_max: Optional end of range in ISO 8601 (defaults to +7 days).
        :param max_results: Max events to return (max 100).
        :return: A formatted list of events, or a connect prompt if the calendar isn't linked.
        """
        payload = {"max_results": max_results}
        if time_min:
            payload["time_min"] = time_min
        if time_max:
            payload["time_max"] = time_max
        data = await self._post("calendar_list_events", payload, self._email(__user__))
        if isinstance(data, dict) and data.get("error"):
            return data["error"]
        events = data.get("events", []) if isinstance(data, dict) else []
        if not events:
            return "No upcoming events found in that range."
        lines = []
        for e in events:
            lines.append(
                f"- **{e.get('title') or e.get('summary', '(untitled)')}** "
                f"{e.get('start', '')}"
                + (f" - {e.get('end')}" if e.get('end') else "")
                + (f"\n  {e.get('location')}" if e.get('location') else "")
                + (f"\n  {e.get('hangout_link') or e.get('meet_link')}" if (e.get('hangout_link') or e.get('meet_link')) else "")
                + f"\n  `event_id: {e.get('id') or e.get('event_id')}`"
            )
        return "\n".join(lines)

    async def create_calendar_event(
        self, title: str, start_time: str, duration_minutes: int = 60,
        description: str = "", attendees: Optional[List[str]] = None,
        add_google_meet: bool = False, timezone: str = None, __user__: dict = {},
    ) -> str:
        """
        Create a Google Calendar event (optionally with attendees and a Google
        Meet link). Use for "schedule ...", "add to my calendar", "set up a
        meeting". Confirm the time with the user if it's ambiguous.

        :param title: Event title.
        :param start_time: Start in ISO 8601, e.g. 2026-08-01T14:00:00.
        :param duration_minutes: Length in minutes (default 60).
        :param description: Optional notes/agenda.
        :param attendees: Optional list of attendee email addresses (they get invited).
        :param add_google_meet: Set true to attach a Google Meet video link.
        :param timezone: IANA timezone (defaults to the configured default).
        :return: Confirmation with the event link, or a connect prompt if not linked.
        """
        payload = {
            "title": title,
            "start_time": start_time,
            "duration_minutes": duration_minutes,
            "description": description or "",
            "add_google_meet": bool(add_google_meet),
            "timezone": timezone or self.valves.default_timezone,
        }
        if attendees:
            payload["attendees"] = attendees
        data = await self._post("calendar_create_event", payload, self._email(__user__))
        if isinstance(data, dict) and data.get("error"):
            return data["error"]
        link = data.get("link") or data.get("html_link") or data.get("event_link") or ""
        meet = data.get("hangout_link") or data.get("meet_link") or ""
        out = f"Event created: **{title}** at {start_time} ({duration_minutes} min)."
        if attendees:
            out += f"\nInvited: {', '.join(attendees)}."
        if meet:
            out += f"\nGoogle Meet: {meet}"
        if link:
            out += f"\nOpen in Calendar: {link}"
        return out

    async def update_calendar_event(
        self, event_id: str, title: str = None, start_time: str = None,
        duration_minutes: int = None, description: str = None,
        add_attendees: Optional[List[str]] = None, __user__: dict = {},
    ) -> str:
        """
        Update an existing calendar event by its id (from a list result). Only
        pass the fields to change.

        :param event_id: The event id (shown as event_id in list results).
        :param title: New title (optional).
        :param start_time: New start in ISO 8601 (optional).
        :param duration_minutes: New duration (optional).
        :param description: New description (optional).
        :param add_attendees: Extra attendee emails to add (optional).
        :return: Confirmation, or a connect prompt if not linked.
        """
        payload = {"event_id": event_id}
        if title is not None:
            payload["title"] = title
        if start_time is not None:
            payload["start_time"] = start_time
        if duration_minutes is not None:
            payload["duration_minutes"] = duration_minutes
        if description is not None:
            payload["description"] = description
        if add_attendees:
            payload["add_attendees"] = add_attendees
        data = await self._post("calendar_update_event", payload, self._email(__user__))
        if isinstance(data, dict) and data.get("error"):
            return data["error"]
        return "Event updated."

    async def delete_calendar_event(
        self, event_id: str, notify_attendees: bool = True, __user__: dict = {},
    ) -> str:
        """
        Delete/cancel a calendar event by its id. Confirm with the user before
        calling this, since it cancels the event.

        :param event_id: The event id to delete.
        :param notify_attendees: Send cancellation notices to attendees (default true).
        :return: Confirmation, or a connect prompt if not linked.
        """
        data = await self._post(
            "calendar_delete_event",
            {"event_id": event_id, "notify_attendees": bool(notify_attendees)},
            self._email(__user__),
        )
        if isinstance(data, dict) and data.get("error"):
            return data["error"]
        return "Event deleted."
