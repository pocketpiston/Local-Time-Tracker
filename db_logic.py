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

def start_timer(project_name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
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

# Initialize db when imported
init_db()
