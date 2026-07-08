-- Add Samsung calendar indexes now enforced at startup by
-- app/core/samsung_calendar.py::init_samsung_calendar_table().

CREATE INDEX IF NOT EXISTS idx_samsung_calendar_end_time
    ON samsung_calendar_events(end_time);

CREATE INDEX IF NOT EXISTS idx_samsung_calendar_synced_at
    ON samsung_calendar_events(synced_at);
