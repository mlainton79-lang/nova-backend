"""Single source of truth for static family facts.

Dates of birth are true constants and belong in code; AGES ARE NEVER
CONSTANTS and must always be computed at call time. This module exists
because hardcoded ages drifted stale ("Margot (9 months)" survived past
her first birthday) and, worse, were recited by providers as if they were
memory — the 15 July recon's "nine months old" wasn't confabulation, it
was a stale constant being read faithfully.

Richer, changeable facts (school dates, preferences, events) live in the
database (tony_facts / memories). This module is only the deterministic
skeleton: names, dates, and helpers that render them freshly.
"""

from datetime import date

# Dates of birth / death — true constants.
MATTHEW_DOB = date(1979, 10, 20)
GEORGINA_DOB = date(1992, 2, 26)
AMELIA_DOB = date(2021, 3, 7)
MARGOT_DOB = date(2025, 7, 20)
DAD_DOB = date(1945, 6, 4)
DAD_PASSED = date(2026, 4, 2)


def _years_between(dob: date, today: date) -> int:
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _months_between(dob: date, today: date) -> int:
    months = (today.year - dob.year) * 12 + (today.month - dob.month)
    if today.day < dob.day:
        months -= 1
    return max(months, 0)


def age_string(dob: date, today: date | None = None) -> str:
    """Human age: months under 2 years, years after."""
    today = today or date.today()
    months = _months_between(dob, today)
    if months < 24:
        return f"{months} month{'s' if months != 1 else ''}"
    return str(_years_between(dob, today))


def daughters_line(today: date | None = None) -> str:
    today = today or date.today()
    return (
        f"Amelia ({age_string(AMELIA_DOB, today)}) and "
        f"Margot ({age_string(MARGOT_DOB, today)})"
    )


def dad_loss_line(today: date | None = None) -> str:
    """Time-honest phrasing for the loss of Matthew's father."""
    today = today or date.today()
    months = _months_between(DAD_PASSED, today)
    if months < 1:
        when = "very recently"
    elif months < 12:
        when = f"{months} month{'s' if months != 1 else ''} ago"
    else:
        years = months // 12
        when = f"{years} year{'s' if years != 1 else ''} ago"
    return f"Lost his father Tony on 2 April 2026 ({when})"


def family_dates(year: int) -> list[tuple[date, str]]:
    """Recurring family dates for the briefing layer."""
    return [
        (date(year, GEORGINA_DOB.month, GEORGINA_DOB.day), "Georgina's birthday"),
        (date(year, AMELIA_DOB.month, AMELIA_DOB.day), "Amelia's birthday"),
        (date(year, MARGOT_DOB.month, MARGOT_DOB.day), "Margot's birthday"),
        (date(year, MATTHEW_DOB.month, MATTHEW_DOB.day), "Matthew's birthday"),
        (date(year, DAD_DOB.month, DAD_DOB.day), "Dad's birthday"),
        (date(year, DAD_PASSED.month, DAD_PASSED.day), "Anniversary of Dad's passing"),
    ]
