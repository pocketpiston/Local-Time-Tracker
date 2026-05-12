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

def update_last_description(description):
    with get_db() as (conn, cursor):
        cursor.execute('''
            UPDATE time_logs
            SET description = ?
            WHERE id = (SELECT MAX(id) FROM time_logs)
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

def get_all_active_timers():
    """Return all rows where is_active = True. Should normally be 0 or 1.
    Useful for debugging orphaned timer issues."""
    with get_db() as (conn, cursor):
        cursor.execute('SELECT * FROM time_logs WHERE is_active = 1')
        return cursor.fetchall()

# Initialize db when imported
init_db()
