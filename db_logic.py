import sqlite3
import datetime
import os
from contextlib import contextmanager

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

def start_timer(project_name, start_time=None):
    if start_time is None:
        start_time = datetime.datetime.now().isoformat()
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
    end_time = datetime.datetime.now().isoformat()
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
        end_iso = datetime.datetime.now().isoformat()
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
    """Reopen the most recent paused row: clear end_time/description, set is_active=1.
    Preserves the original start_time so elapsed time spans the pause gap."""
    with get_db() as (conn, cursor):
        cursor.execute('''
            UPDATE time_logs
            SET end_time = NULL, description = NULL, is_active = 1
            WHERE id = (
                SELECT MAX(id) FROM time_logs
                WHERE is_active = 0 AND description = '[Paused]'
            )
        ''')

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
            SELECT project_name, start_time FROM time_logs
            WHERE is_active = 0 AND description = '[Paused]'
            ORDER BY id DESC LIMIT 1
        ''')
        row = cursor.fetchone()
        if row:
            return {"project_name": row[0], "start_time": row[1]}
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
            SELECT project_name, start_time FROM time_logs WHERE is_active = 1
            ORDER BY id DESC LIMIT 1
        ''')
        row = cursor.fetchone()
        if row:
            return {"project_name": row[0], "start_time": row[1]}
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
        end_time = datetime.datetime.now()
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
        cursor.execute('DELETE FROM time_logs WHERE is_active = 1')
        removed = cursor.rowcount or 0
        if not removed:
            cursor.execute('''
                DELETE FROM time_logs
                WHERE id = (
                    SELECT MAX(id) FROM time_logs
                    WHERE is_active = 0 AND description = '[Paused]'
                )
            ''')
            removed = cursor.rowcount or 0
    return removed


def get_all_active_timers():
    """Return all rows where is_active = True. Should normally be 0 or 1.
    Useful for debugging orphaned timer issues."""
    with get_db() as (conn, cursor):
        cursor.execute('SELECT * FROM time_logs WHERE is_active = 1')
        return cursor.fetchall()

# Initialize db when imported
init_db()
