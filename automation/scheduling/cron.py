"""Small dependency-free cron parser used for local schedule previews.

The accepted expression is the conventional five-field format (minute, hour,
day-of-month, month, day-of-week).  Lists, ranges, and steps are supported.
The parser is intentionally strict so a preview cannot silently differ from a
future scheduler implementation.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class CronError(ValueError):
    pass


def _values(token: str, minimum: int, maximum: int) -> set[int]:
    result: set[int] = set()
    for part in token.split(","):
        if not part:
            raise CronError("Cron contains an empty list item")
        if "/" in part:
            base, raw_step = part.split("/", 1)
            try:
                step = int(raw_step)
            except ValueError as exc:
                raise CronError("Cron step must be an integer") from exc
            if step < 1:
                raise CronError("Cron step must be positive")
        else:
            base, step = part, 1
        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            raw_start, raw_end = base.split("-", 1)
            try:
                start, end = int(raw_start), int(raw_end)
            except ValueError as exc:
                raise CronError("Cron range must contain integers") from exc
        else:
            try:
                start = end = int(base)
            except ValueError as exc:
                raise CronError("Cron values must be integers") from exc
        if start < minimum or end > maximum or start > end:
            raise CronError(f"Cron value must be between {minimum} and {maximum}")
        result.update(range(start, end + 1, step))
    return result


def parse(expression: str) -> tuple[set[int], set[int], set[int], set[int], set[int]]:
    fields = expression.split()
    if len(fields) != 5:
        raise CronError("Cron expression must contain five fields")
    # POSIX accepts Sunday as either 0 or 7.  Expand that alias without
    # rewriting ranges such as ``1-7`` into an invalid descending range.
    dow_parts = []
    for part in fields[4].split(","):
        if part == "7":
            dow_parts.append("0")
        elif part.startswith("7/"):
            dow_parts.append("0" + part[1:])
        else:
            dow_parts.append(part)
    return (
        _values(fields[0], 0, 59),
        _values(fields[1], 0, 23),
        _values(fields[2], 1, 31),
        _values(fields[3], 1, 12),
        _values(",".join(dow_parts), 0, 6),
    )


def next_occurrences(expression: str, after: datetime, count: int = 5) -> list[datetime]:
    if count < 1 or count > 100:
        raise CronError("Preview count must be between 1 and 100")
    minute, hour, monthday, month, weekday = parse(expression)
    try:
        zone = ZoneInfo(str(after.tzinfo)) if after.tzinfo and isinstance(after.tzinfo, ZoneInfo) else ZoneInfo("UTC")
    except ZoneInfoNotFoundError as exc:
        raise CronError("Unknown timezone") from exc
    cursor = after.astimezone(zone).replace(second=0, microsecond=0) + timedelta(minutes=1)
    found: list[datetime] = []
    # A five-field cron can legitimately have sparse dates; two years is ample
    # for a user-facing preview while keeping malformed expressions bounded.
    for _ in range(60 * 24 * 366 * 2):
        day_matches = cursor.day in monthday
        month_matches = cursor.month in month
        weekday_matches = cursor.weekday() in weekday
        # Standard cron uses OR when both day-of-month and day-of-week are
        # restricted; with either wildcard the other field controls matching.
        dom_wild = len(monthday) == 31
        dow_wild = len(weekday) == 7
        day_matches = (weekday_matches if dom_wild else day_matches if dow_wild else day_matches or weekday_matches)
        if cursor.minute in minute and cursor.hour in hour and month_matches and day_matches:
            found.append(cursor)
            if len(found) == count:
                return found
        cursor += timedelta(minutes=1)
    raise CronError("Cron expression produced no occurrence in the preview window")


def preview_schedule(schedule, *, after: datetime, count: int = 5) -> list[datetime]:
    """Return timezone-aware occurrences for a preset or custom cron schedule."""

    try:
        zone = ZoneInfo(schedule.timezone)
    except ZoneInfoNotFoundError as exc:
        raise CronError(f"Unknown timezone: {schedule.timezone}") from exc
    base = after.astimezone(zone) if after.tzinfo else after.replace(tzinfo=zone)
    if schedule.frequency.value == "cron":
        return next_occurrences(schedule.cron_expression, base, count)
    result: list[datetime] = []
    cursor = base.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(60 * 24 * 366 * 3):
        matches = cursor.hour == schedule.hour and cursor.minute == schedule.minute
        if schedule.frequency.value == "weekly":
            matches = matches and cursor.weekday() == schedule.weekday
        elif schedule.frequency.value == "monthly":
            matches = matches and cursor.day == schedule.monthday
        if schedule.frequency.value == "daily" and matches:
            result.append(cursor)
        elif schedule.frequency.value in {"weekly", "monthly"} and matches:
            result.append(cursor)
        if len(result) == count:
            return result
        cursor += timedelta(minutes=1)
    raise CronError("Schedule produced no occurrence in the preview window")
