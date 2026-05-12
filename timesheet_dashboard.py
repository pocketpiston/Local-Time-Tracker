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

edited_df = st.data_editor(df, num_rows="dynamic", key="data_editor", width="stretch")

if st.button("Save Changes to Database"):
    save_data(df, edited_df)
    st.success("Changes successfully saved to the database!")
    st.rerun()

st.header("Summary")
if not df.empty and 'duration_hours' in df.columns and not df['duration_hours'].isna().all():
    completed_df = df.dropna(subset=['start_time', 'end_time', 'duration_hours']).copy()
    
    if not completed_df.empty:
        filter_type = st.radio("Filter By", ["All Time", "Week", "Month", "Year", "Custom Range"], horizontal=True)
        
        now = pd.Timestamp.now().normalize()
        start_date = None
        end_date = None
        
        if filter_type == "Week":
            week_options = ["This Week", "Last Week", "2 Weeks Ago", "3 Weeks Ago", "4 Weeks Ago"]
            display_options = []
            week_ranges = {}
            for i, opt in enumerate(week_options):
                # Monday
                s_date = now - pd.to_timedelta(now.dayofweek + (i * 7), unit='d')
                # Friday
                e_date = s_date + pd.to_timedelta(4, unit='d') 
                
                display_str = f"{opt} ({s_date.strftime('%b %d')} - {e_date.strftime('%b %d')})"
                display_options.append(display_str)
                week_ranges[display_str] = (s_date, e_date)
            
            selected_week_display = st.selectbox("Select Week", display_options)
            start_date, end_date = week_ranges[selected_week_display]
            
        elif filter_type == "Month":
            import datetime
            local_tz = datetime.datetime.now().astimezone().tzinfo
            
            # Extract unique months from the dataset
            local_times = pd.to_datetime(completed_df['start_time'], utc=True).dt.tz_convert(local_tz)
            available_months = local_times.dt.tz_localize(None).dt.to_period('M').unique()
            
            # Sort descending to show newest first
            sorted_months = pd.Series(available_months).sort_values(ascending=False)
            month_options = [m.strftime("%B %Y") for m in sorted_months]
            
            # Fallback if no options are present
            if not month_options:
                month_options = [now.strftime("%B %Y")]
                
            month_option = st.selectbox("Select Month", month_options)
            
            # Parse the selected month
            selected_period = pd.Period(month_option, freq='M')
            start_date = selected_period.start_time.normalize()
            end_date = selected_period.end_time.normalize()
            
        elif filter_type == "Year":
            import datetime
            local_tz = datetime.datetime.now().astimezone().tzinfo
            
            # Extract unique years from the dataset
            local_times = pd.to_datetime(completed_df['start_time'], utc=True).dt.tz_convert(local_tz)
            available_years = local_times.dt.year.unique()
            
            # Sort descending
            sorted_years = pd.Series(available_years).sort_values(ascending=False)
            year_options = [str(y) for y in sorted_years]
            
            if not year_options:
                year_options = [str(now.year)]
                
            year_option = st.selectbox("Select Year", year_options)
            
            target_year = int(year_option)
            start_date = pd.Timestamp(year=target_year, month=1, day=1)
            end_date = pd.Timestamp(year=target_year, month=12, day=31)
            
        elif filter_type == "Custom Range":
            custom_dates = st.date_input("Select Date Range", value=(now.date() - pd.Timedelta(days=7), now.date()))
            if isinstance(custom_dates, tuple):
                if len(custom_dates) == 2:
                    start_date = pd.Timestamp(custom_dates[0])
                    end_date = pd.Timestamp(custom_dates[1])
                elif len(custom_dates) == 1:
                    start_date = pd.Timestamp(custom_dates[0])
                    end_date = start_date
            else:
                start_date = pd.Timestamp(custom_dates)
                end_date = start_date
                
        import datetime
        local_tz = datetime.datetime.now().astimezone().tzinfo
        compare_times = pd.to_datetime(completed_df['start_time'], utc=True)
        filtered_df = completed_df
        
        if start_date is not None:
            start_date_utc = start_date.tz_localize(local_tz).tz_convert('UTC')
            filtered_df = filtered_df[compare_times >= start_date_utc]
            
        if end_date is not None and not filtered_df.empty:
            # End date should be inclusive of the entire day
            end_date_inclusive = end_date + pd.to_timedelta(1, unit='d')
            end_date_utc = end_date_inclusive.tz_localize(local_tz).tz_convert('UTC')
            
            # Recalculate compare_times for the filtered dataframe
            compare_times_end = pd.to_datetime(filtered_df['start_time'], utc=True)
            filtered_df = filtered_df[compare_times_end < end_date_utc]

        if not filtered_df.empty:
            total_hours = filtered_df['duration_hours'].sum()
            most_active_project = filtered_df.groupby('project_name')['duration_hours'].sum().idxmax()
            entries_count = len(filtered_df)
            
            mcol1, mcol2, mcol3 = st.columns(3)
            mcol1.metric("Total Hours", f"{total_hours:.2f}h")
            mcol2.metric("Top Project", most_active_project)
            mcol3.metric("Completed Entries", entries_count)
            
            st.subheader("Time per Project")
            summary_df = filtered_df.groupby('project_name')['duration_hours'].sum().reset_index()
            st.bar_chart(summary_df.set_index('project_name'))
            
            colA, colB = st.columns([3, 1])
            with colA:
                st.subheader("Trend over Time")
            with colB:
                group_by = st.selectbox("Group By", ["Day", "Week", "Month"], label_visibility="collapsed")
            
            time_df = filtered_df.copy()
            # Convert to UTC first to safely extract formatting, avoiding mixed offset errors
            plot_time = pd.to_datetime(time_df['start_time'], utc=True)
            
            if group_by == "Day":
                time_df['period'] = plot_time.dt.strftime('%Y-%m-%d')
            elif group_by == "Week":
                time_df['period'] = plot_time.dt.strftime('%G-W%V')
            elif group_by == "Month":
                time_df['period'] = plot_time.dt.strftime('%Y-%m')
                
            time_summary = time_df.groupby(['period', 'project_name'])['duration_hours'].sum().unstack(fill_value=0)
            st.bar_chart(time_summary)
            
        else:
            st.write("No completed time logs available for the selected period.")
    else:
        st.write("No completed time logs available for summary.")
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
