import streamlit as st
import pandas as pd
import sqlite3
import db_logic

DB_NAME = db_logic.DB_NAME

st.set_page_config(page_title="Local Time Tracker", page_icon="⏱️")
st.title("Time Tracker Dashboard")

def load_data():
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM time_logs", conn)
    conn.close()
    
    if not df.empty:
        # Convert string to datetime objects
        df['start_time'] = pd.to_datetime(df['start_time'], format='ISO8601')
        df['end_time'] = pd.to_datetime(df['end_time'], format='ISO8601')
        
        # Calculate duration in hours
        df['duration_hours'] = (df['end_time'] - df['start_time']).dt.total_seconds() / 3600.0
    else:
        df['duration_hours'] = pd.Series(dtype=float)
        
    return df

def save_data(original_df, edited_df):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # 1. Handle DELETIONS
    # Any ID that was in original_df but is missing from edited_df got deleted
    if not original_df.empty:
        original_ids = set(original_df['id'].dropna().astype(int))
    else:
        original_ids = set()
        
    if not edited_df.empty:
        current_ids = set(edited_df['id'].dropna().astype(int))
    else:
        current_ids = set()
        
    deleted_ids = original_ids - current_ids
    for d_id in deleted_ids:
        cursor.execute('DELETE FROM time_logs WHERE id = ?', (int(d_id),))
        
    # 2. Handle UPDATES and INSERTIONS
    if not edited_df.empty:
        for index, row in edited_df.iterrows():
            # Clean up all types to avoid Pandas NaT/NaN SQLite crashes
            proj = str(row['project_name']) if pd.notna(row['project_name']) else ""
            desc = str(row['description']) if pd.notna(row['description']) else ""
            is_active = bool(row['is_active']) if pd.notna(row['is_active']) else False
            
            start_time = row['start_time'].isoformat() if pd.notna(row['start_time']) else None
            end_time = row['end_time'].isoformat() if pd.notna(row['end_time']) else None
            
            # Check if row is essentially empty
            if not proj.strip() and start_time is None and end_time is None and not desc.strip():
                if not pd.isna(row['id']):
                    cursor.execute('DELETE FROM time_logs WHERE id = ?', (int(row['id']),))
                continue
            
            if pd.isna(row['id']):
                # This is a brand new row added via the UI
                cursor.execute('''
                    INSERT INTO time_logs (project_name, start_time, end_time, description, is_active)
                    VALUES (?, ?, ?, ?, ?)
                ''', (proj, start_time, end_time, desc, is_active))
            else:
                # Update an existing row
                cursor.execute('''
                    UPDATE time_logs 
                    SET project_name = ?, start_time = ?, end_time = ?, description = ?, is_active = ?
                    WHERE id = ?
                ''', (proj, start_time, end_time, desc, is_active, int(row['id'])))
                
    conn.commit()
    conn.close()

df = load_data()

st.header("Time Logs")
st.write("Edit the table below to correct any typos or timestamps. Changes require a manual save.")

edited_df = st.data_editor(df, num_rows="dynamic", key="data_editor", use_container_width=True)

if st.button("Save Changes to Database"):
    save_data(df, edited_df)
    st.success("Changes successfully saved to the database!")
    st.rerun()

st.header("Summary")
if not df.empty and 'duration_hours' in df.columns and not df['duration_hours'].isna().all():
    summary_df = df.groupby('project_name')['duration_hours'].sum().reset_index()
    st.bar_chart(summary_df.set_index('project_name'))
else:
    st.write("No completed time logs available for summary.")

st.header("Export Data")
if not df.empty:
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="Download data as CSV",
        data=csv,
        file_name='timesheet.csv',
        mime='text/csv',
    )
else:
    st.write("No data available to export.")
