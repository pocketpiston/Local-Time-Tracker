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
        df['start_time'] = pd.to_datetime(df['start_time'])
        df['end_time'] = pd.to_datetime(df['end_time'])
        
        # Calculate duration in hours
        df['duration_hours'] = (df['end_time'] - df['start_time']).dt.total_seconds() / 3600.0
    else:
        df['duration_hours'] = pd.Series(dtype=float)
        
    return df

def save_data(edited_df):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    for index, row in edited_df.iterrows():
        # Handle potentially NaT/NaN values
        start_time = row['start_time'].isoformat() if pd.notnull(row['start_time']) else None
        end_time = row['end_time'].isoformat() if pd.notnull(row['end_time']) else None
        
        cursor.execute('''
            UPDATE time_logs 
            SET project_name = ?, start_time = ?, end_time = ?, description = ?, is_active = ?
            WHERE id = ?
        ''', (
            row['project_name'], 
            start_time, 
            end_time, 
            row['description'], 
            bool(row['is_active']),
            row['id']
        ))
    conn.commit()
    conn.close()

df = load_data()

st.header("Time Logs")
st.write("Edit the table below to correct any typos or timestamps. Changes require a manual save.")

edited_df = st.data_editor(df, num_rows="dynamic", key="data_editor", use_container_width=True)

if st.button("Save Changes to Database"):
    save_data(edited_df)
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
