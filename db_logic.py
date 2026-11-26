import sqlite3
import datetime
import os
from contextlib import contextmanager

PAUSED = '[Paused]'

DB_NAME = os.path.join(os.path.dirname(__file__), 'time_tracker.db')

@contextmanager
def get_db():
    """Yield a (conn, cursor) pair and auto-commit/close."""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        yield conn, cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with get_db() as (conn, cursor):
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS time_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT,
                start_time TEXT,
                end_time TEXT,
                description TEXT,
                is_active BOOLEAN
            )
        ''')
        # One row per finished break inside an entry. Additive migration: rows
        # logged before this table existed simply have no pauses, so their
        # duration (end - start) is unchanged.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pauses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                log_id INTEGER NOT NULL REFERENCES time_logs(id) ON DELETE CASCADE,
                pause_start TEXT NOT NULL,
                pause_end TEXT NOT NULL
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_pauses_log ON pauses(log_id)')


# ── Worked time ────────────────────────────────────────────────────
# An entry is one row spanning start_time → end_time. Breaks taken with
# Pause/Resume are stored in `pauses` and are NOT worked time. Everything that
# turns an entry into hours goes through these helpers.

def _dt(value):
    if value is None or isinstance(value, datetime.datetime):
        return value
    return datetime.datetime.fromisoformat(value)


def work_periods(start, end, pauses=()):
    """The worked intervals of [start, end) once the pauses are cut out.

    11:30→13:30 with a 12:00→13:00 pause gives [(11:30, 12:00), (13:00, 13:30)].
    Pauses are clipped to the entry, so moving its start or end past a pause
    (stop dialog, dashboard edit) never produces negative time.
    """
    start, end = _dt(start), _dt(end)
    if start is None or end is None or end <= start:
        return []
    periods, cur = [], start
    for ps, pe in sorted((_dt(a), _dt(b)) for a, b in pauses):
        ps, pe = max(ps, start), min(pe, end)
        if pe <= ps or pe <= cur:
            continue
        if ps > cur:
            periods.append((cur, ps))
        cur = max(cur, pe)
    if cur < end:
        periods.append((cur, end))
    return periods


def worked_seconds(start, end, pauses=()):
    return sum((e - s).total_seconds() for s, e in work_periods(start, end, pauses))


def end_for_worked(start, hours, pauses=()):
    """The end time at which an entry starting at `start` has `hours` worked.

    Used when a duration is typed: 1.0 h from 11:30 with a 12:00→13:00 break
    ends at 13:30, not 12:30.
    """
    cur = _dt(start)
    remaining = datetime.timedelta(hours=hours)
    for ps, pe in sorted((_dt(a), _dt(b)) for a, b in pauses):
        if pe <= cur:
            continue
        ps = max(ps, cur)
        if cur + remaining <= ps:
            break
        remaining -= ps - cur
        cur = pe
    return cur + remaining


def fmt_periods(start, end, pauses=()):
    """'11:30 AM–12:00 PM + 1:00–1:30 PM' — the worked periods, for display."""
    def t(d):
        return d.strftime('%-I:%M %p')
    return " + ".join(f"{t(a)}–{t(b)}" for a, b in work_periods(start, end, pauses))


def get_pauses(log_id, cursor=None):
    """[(pause_start, pause_end)] ISO strings for one entry, oldest first."""
    if cursor is None:
        with get_db() as (_conn, cur):
            return get_pauses(log_id, cur)
    cursor.execute('SELECT pause_start, pause_end FROM pauses WHERE log_id = ? '
                   'ORDER BY pause_start', (log_id,))
    return cursor.fetchall()


def pauses_by_log(cursor=None):
    """{log_id: [(pause_start, pause_end), ...]} for every entry with a pause."""
    if cursor is None:
        with get_db() as (_conn, cur):
            return pauses_by_log(cur)
    cursor.execute('SELECT log_id, pause_start, pause_end FROM pauses ORDER BY pause_start')
    out = {}
    for log_id, ps, pe in cursor.fetchall():
        out.setdefault(log_id, []).append((ps, pe))
    return out


def _now():
    """Single clock seam so tests can pin the time."""
    return datetime.datetime.now()

def start_timer(project_name, start_time=None):
    if start_time is None:
        start_time = _now().isoformat()
    with get_db() as (conn, cursor):
        # Safety: stop any orphaned active timers first
        cursor.execute('''
            UPDATE time_logs SET end_time = ?, description = COALESCE(description, ''), is_active = 0
            WHERE is_active = 1
        ''', (start_time,))
        # Insert new log
        cursor.execute('''
            INSERT INTO time_logs (project_name, start_time, is_active)
            VALUES (?, ?, 1)
        ''', (project_name, start_time))

def stop_timer(description):
    end_time = _now().isoformat()
    with get_db() as (conn, cursor):
        cursor.execute('''
            UPDATE time_logs
            SET end_time = ?, description = ?, is_active = 0
            WHERE id = (SELECT MAX(id) FROM time_logs WHERE is_active = 1)
        ''', (end_time, description))

def stop_timer_with(description, start_iso=None, end_iso=None, project=None):
    """Stop the active timer, optionally correcting its times and project.

    Used by the desktop timer window, where the stop dialog lets you fix the
    session before saving it. Any argument left as None keeps the stored value.
    """
    if end_iso is None:
        end_iso = _now().isoformat()
    with get_db() as (conn, cursor):
        cursor.execute('''
            UPDATE time_logs
            SET end_time = ?,
                description = ?,
                is_active = 0,
                start_time = COALESCE(?, start_time),
                project_name = COALESCE(?, project_name)
            WHERE id = (SELECT MAX(id) FROM time_logs WHERE is_active = 1)
        ''', (end_iso, description, start_iso, project))


def update_last_entry(description, start_iso=None, end_iso=None, project=None):
    """Finalise the paused entry, optionally correcting times and project.

    Targets the paused row, not MAX(id): a newer row — a manual entry, or one
    added from the dashboard — would otherwise be overwritten instead.
    """
    with get_db() as (conn, cursor):
        cursor.execute('''
            UPDATE time_logs
            SET description = ?,
                start_time = COALESCE(?, start_time),
                end_time = COALESCE(?, end_time),
                project_name = COALESCE(?, project_name)
            WHERE id = (
                SELECT MAX(id) FROM time_logs
                WHERE is_active = 0 AND description = '[Paused]'
            )
        ''', (description, start_iso, end_iso, project))


def resume_paused_timer():
    """Reopen the paused entry and record the break it just finished.

    The row keeps its original start_time (it is still one entry), but the gap
    from the moment it was paused (its end_time) to now goes into `pauses`, so
    worked time is Period 1 + Period 2, not the whole span. Before the pauses
    table existed this simply reopened the row, which counted the break as work.
    """
    now = _now().isoformat()
    with get_db() as (conn, cursor):
        cursor.execute('''
            SELECT id, end_time FROM time_logs
            WHERE is_active = 0 AND description = ?
            ORDER BY id DESC LIMIT 1
        ''', (PAUSED,))
        row = cursor.fetchone()
        if not row:
            return False
        log_id, paused_at = row
        if paused_at and paused_at < now:
            cursor.execute('INSERT INTO pauses (log_id, pause_start, pause_end) '
                           'VALUES (?, ?, ?)', (log_id, paused_at, now))
        cursor.execute('''
            UPDATE time_logs SET end_time = NULL, description = NULL, is_active = 1
            WHERE id = ?
        ''', (log_id,))
        return True

def get_paused_timer():
    """Return the pause still in progress, if there is one.

    Identified as the newest '[Paused]' row, NOT as the newest row overall.
    Testing id = MAX(id) made the pause vanish as soon as anything else was
    written — logging hours manually, or adding an entry from the dashboard —
    stranding a row that could no longer be resumed or stopped. Resuming and
    stopping both clear the placeholder, so any '[Paused]' row left in the
    table is by definition an unfinished pause. This now matches the condition
    resume_paused_timer() has always used.
    """
    with get_db() as (conn, cursor):
        cursor.execute('''
            SELECT id, project_name, start_time, end_time FROM time_logs
            WHERE is_active = 0 AND description = '[Paused]'
            ORDER BY id DESC LIMIT 1
        ''')
        row = cursor.fetchone()
        if row:
            return {"id": row[0], "project_name": row[1], "start_time": row[2],
                    "end_time": row[3], "pauses": get_pauses(row[0], cursor)}
        return None

def update_last_description(description):
    """Finalise the paused entry by replacing its '[Paused]' placeholder.

    Targets the paused row rather than MAX(id): with a newer row present this
    used to write the description onto that one instead, so stopping a paused
    timer overwrote an unrelated entry.
    """
    with get_db() as (conn, cursor):
        cursor.execute('''
            UPDATE time_logs
            SET description = ?
            WHERE id = (
                SELECT MAX(id) FROM time_logs
                WHERE is_active = 0 AND description = '[Paused]'
            )
        ''', (description,))

def get_active_timer():
    with get_db() as (conn, cursor):
        cursor.execute('''
            SELECT id, project_name, start_time FROM time_logs WHERE is_active = 1
            ORDER BY id DESC LIMIT 1
        ''')
        row = cursor.fetchone()
        if row:
            return {"id": row[0], "project_name": row[1], "start_time": row[2],
                    "pauses": get_pauses(row[0], cursor)}
        return None

def get_last_ended_timer():
    with get_db() as (conn, cursor):
        cursor.execute('''
            SELECT project_name, end_time FROM time_logs WHERE is_active = 0
            ORDER BY id DESC LIMIT 1
        ''')
        row = cursor.fetchone()
        if row:
            return {"project_name": row[0], "end_time": row[1]}
        return None

def set_active_start_time(new_start_time_iso):
    with get_db() as (conn, cursor):
        cursor.execute('''
            UPDATE time_logs SET start_time = ?
            WHERE id = (SELECT MAX(id) FROM time_logs WHERE is_active = 1)
        ''', (new_start_time_iso,))

def add_manual_log(project_name, hours, description="", end_time=None):
    """Insert a completed (non-active) entry whose duration is `hours` hours,
    ending at end_time (defaults to now)."""
    if end_time is None:
        end_time = _now()
    start_time = end_time - datetime.timedelta(hours=hours)
    with get_db() as (conn, cursor):
        cursor.execute('''
            INSERT INTO time_logs (project_name, start_time, end_time, description, is_active)
            VALUES (?, ?, ?, ?, 0)
        ''', (project_name, start_time.isoformat(), end_time.isoformat(), description))

def discard_active_timer():
    """Delete a running or just-paused timer without recording an entry.

    For a timer started by mistake. Returns the number of rows removed. The
    paused branch removes the same row get_paused_timer() reports, so whatever
    the window shows as paused is what Discard takes away; keying it on MAX(id)
    instead left the app offering to discard a pause it could not then delete.
    Only a '[Paused]' placeholder is ever removed — never a finished entry.
    """
    with get_db() as (conn, cursor):
        cursor.execute('SELECT id FROM time_logs WHERE is_active = 1')
        ids = [r[0] for r in cursor.fetchall()]
        if not ids:
            cursor.execute('''
                SELECT MAX(id) FROM time_logs
                WHERE is_active = 0 AND description = '[Paused]'
            ''')
            ids = [r[0] for r in cursor.fetchall() if r[0] is not None]
        for log_id in ids:
            cursor.execute('DELETE FROM pauses WHERE log_id = ?', (log_id,))
            cursor.execute('DELETE FROM time_logs WHERE id = ?', (log_id,))
        removed = len(ids)
    return removed


def delete_pauses_for(log_ids, cursor):
    """Drop the breaks of deleted entries (SQLite leaves FKs unenforced)."""
    for log_id in log_ids:
        cursor.execute('DELETE FROM pauses WHERE log_id = ?', (int(log_id),))


def get_all_active_timers():
    """Return all rows where is_active = True. Should normally be 0 or 1.
    Useful for debugging orphaned timer issues."""
    with get_db() as (conn, cursor):
        cursor.execute('SELECT * FROM time_logs WHERE is_active = 1')
        return cursor.fetchall()

# Initialize db when imported
init_db()
