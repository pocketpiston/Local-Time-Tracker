import sqlite3
import datetime
import os

DB_NAME = os.path.join(os.path.dirname(__file__), 'time_tracker.db')

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
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
    conn.commit()
    conn.close()

def start_timer(project_name, start_time=None):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    if start_time is None:
        start_time = datetime.datetime.now().isoformat()
    # Insert new log
    cursor.execute('''
        INSERT INTO time_logs (project_name, start_time, is_active)
        VALUES (?, ?, ?)
    ''', (project_name, start_time, True))
    conn.commit()
    conn.close()

def stop_timer(description):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    end_time = datetime.datetime.now().isoformat()
    cursor.execute('''
        UPDATE time_logs
        SET end_time = ?, description = ?, is_active = ?
        WHERE is_active = ?
    ''', (end_time, description, False, True))
    conn.commit()
    conn.close()

def update_last_description(description):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE time_logs
        SET description = ?
        WHERE id = (SELECT MAX(id) FROM time_logs)
    ''', (description,))
    conn.commit()
    conn.close()

def get_active_timer():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT project_name, start_time FROM time_logs WHERE is_active = ?
    ''', (True,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"project_name": row[0], "start_time": row[1]}
    return None

def get_last_ended_timer():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT project_name, end_time FROM time_logs WHERE is_active = ? ORDER BY id DESC LIMIT 1
    ''', (False,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"project_name": row[0], "end_time": row[1]}
    return None

def adjust_active_start_time(mins_to_subtract):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, start_time FROM time_logs WHERE is_active = ?
    ''', (True,))
    row = cursor.fetchone()
    if row:
        log_id, start_time_str = row
        import datetime
        dt = datetime.datetime.fromisoformat(start_time_str)
        new_dt = dt - datetime.timedelta(minutes=mins_to_subtract)
        cursor.execute('''
            UPDATE time_logs SET start_time = ? WHERE id = ?
        ''', (new_dt.isoformat(), log_id))
        conn.commit()
    conn.close()

def set_active_start_time(new_start_time_iso):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE time_logs SET start_time = ? WHERE is_active = ?
    ''', (new_start_time_iso, True))
    conn.commit()
    conn.close()

# Initialize db when imported
init_db()
