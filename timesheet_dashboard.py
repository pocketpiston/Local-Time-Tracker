import streamlit as st
import pandas as pd
import sqlite3
import datetime
import db_logic

DB_NAME = db_logic.DB_NAME

st.set_page_config(
    page_title="Local Time Tracker",
    page_icon="⏱️",
    layout="wide",
)

# ── Custom Styling ──────────────────────────────────────────────────
st.markdown("""
<style>
    /* Import a clean font */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    /* Apply font globally */
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    /* Tighten main container padding */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    
    /* Style metric cards — light, clean, high contrast */
    [data-testid="stMetric"] {
        background: #f0f2f6;
        border: 1px solid #d1d5db;
        border-radius: 12px;
        padding: 1rem 1.25rem;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: #6b7280 !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 1.6rem;
        font-weight: 700;
        color: #111827 !important;
    }
    
    /* Dark mode overrides */
    @media (prefers-color-scheme: dark) {
        [data-testid="stMetric"] {
            background: #1e1e2e;
            border-color: #3b3b4f;
        }
        [data-testid="stMetricLabel"] {
            color: #a1a1aa !important;
        }
        [data-testid="stMetricValue"] {
            color: #f4f4f5 !important;
        }
    }
    /* Streamlit dark theme class override */
    [data-testid="stAppViewContainer"][data-theme="dark"] [data-testid="stMetric"],
    .stApp[data-theme="dark"] [data-testid="stMetric"] {
        background: #1e1e2e;
        border-color: #3b3b4f;
    }
    
    /* Divider styling */
    hr {
        border: none;
        border-top: 1px solid #e5e7eb;
        margin: 2rem 0;
    }
    
    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0.5rem;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px;
        padding: 0.5rem 1rem;
    }
    
    /* Preview box styling */
    .preview-box {
        background: #f0f2f6;
        border: 1px solid #d1d5db;
        border-radius: 8px;
        padding: 0.75rem 1rem;
        margin: 0.5rem 0;
        color: #111827;
    }
</style>
""", unsafe_allow_html=True)


# ── Data Loading ────────────────────────────────────────────────────
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
        df.loc[df['duration_hours'] < 0, 'duration_hours'] = 0  # clamp negatives
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


# ── Load Data ───────────────────────────────────────────────────────
df = load_data()

# ── Page Header ─────────────────────────────────────────────────────
header_col1, header_col2 = st.columns([5, 1])
with header_col1:
    st.title("⏱️ Time Tracker")
    st.caption("Track, review, and export your working hours — all stored locally.")
with header_col2:
    st.write("")  # spacing
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()

st.divider()

# ── Quick Stats (always visible at top) ─────────────────────────────
if not df.empty:
    completed = df.dropna(subset=['start_time', 'end_time', 'duration_hours']).copy()
    completed = completed[completed['description'] != '[Paused]']
    
    if not completed.empty:
        now = pd.Timestamp.now().normalize()
        # This week (Mon–Fri)
        week_start = now - pd.to_timedelta(now.dayofweek, unit='d')
        local_tz = datetime.datetime.now().astimezone().tzinfo
        week_start_utc = week_start.tz_localize(local_tz).tz_convert('UTC')
        compare_times = pd.to_datetime(completed['start_time'], utc=True)
        this_week = completed[compare_times >= week_start_utc]
        
        # Today
        today_start_utc = now.tz_localize(local_tz).tz_convert('UTC')
        today = completed[compare_times >= today_start_utc]
        
        q1, q2, q3, q4 = st.columns(4)
        q1.metric("Today", f"{today['duration_hours'].sum():.1f}h")
        q2.metric("This Week", f"{this_week['duration_hours'].sum():.1f}h")
        q3.metric("All Time", f"{completed['duration_hours'].sum():.1f}h")
        q4.metric("Total Entries", f"{len(completed)}")
        
        st.divider()

# ── Tabbed Interface ────────────────────────────────────────────────
tab_summary, tab_logs, tab_add, tab_export = st.tabs([
    "📊 Summary", 
    "📋 Time Logs", 
    "➕ Add Entry", 
    "📥 Export"
])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB: Summary
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_summary:
    if not df.empty and 'duration_hours' in df.columns and not df['duration_hours'].isna().all():
        completed_df = df.dropna(subset=['start_time', 'end_time', 'duration_hours']).copy()
        completed_df = completed_df[completed_df['description'] != '[Paused]']
        
        if not completed_df.empty:
            filter_type = st.radio(
                "Filter By", 
                ["All Time", "Week", "Month", "Year", "Custom Range"], 
                horizontal=True,
                key="summary_filter"
            )
            
            now = pd.Timestamp.now().normalize()
            start_date = None
            end_date = None
            
            if filter_type == "Week":
                week_options = ["This Week", "Last Week", "2 Weeks Ago", "3 Weeks Ago", "4 Weeks Ago"]
                display_options = []
                week_ranges = {}
                for i, opt in enumerate(week_options):
                    s_date = now - pd.to_timedelta(now.dayofweek + (i * 7), unit='d')
                    e_date = s_date + pd.to_timedelta(4, unit='d') 
                    display_str = f"{opt} ({s_date.strftime('%b %d')} – {e_date.strftime('%b %d')})"
                    display_options.append(display_str)
                    week_ranges[display_str] = (s_date, e_date)
                
                selected_week_display = st.selectbox("Select Week", display_options, key="summary_week")
                start_date, end_date = week_ranges[selected_week_display]
                
            elif filter_type == "Month":
                local_tz = datetime.datetime.now().astimezone().tzinfo
                local_times = pd.to_datetime(completed_df['start_time'], utc=True).dt.tz_convert(local_tz)
                available_months = local_times.dt.tz_localize(None).dt.to_period('M').unique()
                sorted_months = pd.Series(available_months).sort_values(ascending=False)
                month_options = [m.strftime("%B %Y") for m in sorted_months]
                if not month_options:
                    month_options = [now.strftime("%B %Y")]
                month_option = st.selectbox("Select Month", month_options, key="summary_month")
                selected_period = pd.Period(month_option, freq='M')
                start_date = selected_period.start_time.normalize()
                end_date = selected_period.end_time.normalize()
                
            elif filter_type == "Year":
                local_tz = datetime.datetime.now().astimezone().tzinfo
                local_times = pd.to_datetime(completed_df['start_time'], utc=True).dt.tz_convert(local_tz)
                available_years = local_times.dt.year.unique()
                sorted_years = pd.Series(available_years).sort_values(ascending=False)
                year_options = [str(y) for y in sorted_years]
                if not year_options:
                    year_options = [str(now.year)]
                year_option = st.selectbox("Select Year", year_options, key="summary_year")
                target_year = int(year_option)
                start_date = pd.Timestamp(year=target_year, month=1, day=1)
                end_date = pd.Timestamp(year=target_year, month=12, day=31)
                
            elif filter_type == "Custom Range":
                custom_dates = st.date_input(
                    "Select Date Range", 
                    value=(now.date() - pd.Timedelta(days=7), now.date()),
                    key="summary_custom"
                )
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
                    
            # Apply date filter
            local_tz = datetime.datetime.now().astimezone().tzinfo
            compare_times = pd.to_datetime(completed_df['start_time'], utc=True)
            filtered_df = completed_df
            
            if start_date is not None:
                start_date_utc = start_date.tz_localize(local_tz).tz_convert('UTC')
                filtered_df = filtered_df[compare_times >= start_date_utc]
                
            if end_date is not None and not filtered_df.empty:
                end_date_inclusive = end_date + pd.to_timedelta(1, unit='d')
                end_date_utc = end_date_inclusive.tz_localize(local_tz).tz_convert('UTC')
                compare_times_end = pd.to_datetime(filtered_df['start_time'], utc=True)
                filtered_df = filtered_df[compare_times_end < end_date_utc]

            if not filtered_df.empty:
                total_hours = filtered_df['duration_hours'].sum()
                most_active_project = filtered_df.groupby('project_name')['duration_hours'].sum().idxmax()
                entries_count = len(filtered_df)
                avg_daily = total_hours / max((filtered_df['start_time'].max() - filtered_df['start_time'].min()).days, 1)
                
                mcol1, mcol2, mcol3, mcol4 = st.columns(4)
                mcol1.metric("Total Hours", f"{total_hours:.1f}h")
                mcol2.metric("Top Project", most_active_project)
                mcol3.metric("Entries", entries_count)
                mcol4.metric("Avg / Day", f"{avg_daily:.1f}h")
                
                st.write("")  # spacing
                
                # Charts side by side
                chart_col1, chart_col2 = st.columns(2)
                
                with chart_col1:
                    st.subheader("Hours by Project")
                    summary_df = filtered_df.groupby('project_name')['duration_hours'].sum().reset_index()
                    summary_df.columns = ['Project', 'Hours']
                    st.bar_chart(summary_df.set_index('Project'), color="#5E72E4")
                
                with chart_col2:
                    colA, colB = st.columns([3, 1])
                    with colA:
                        st.subheader("Trend")
                    with colB:
                        group_by = st.selectbox(
                            "Group By", ["Day", "Week", "Month"], 
                            label_visibility="collapsed",
                            key="summary_group"
                        )
                    
                    time_df = filtered_df.copy()
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
                st.info("No entries found for the selected period.", icon="📭")
        else:
            st.info("No completed time logs yet. Start tracking to see your summary!", icon="📭")
    else:
        st.info("No time data available. Start tracking to see your summary!", icon="📭")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB: Time Logs
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_logs:
    st.caption("Double-click any cell to edit. Add rows at the bottom, delete by selecting and pressing `Delete`.")
    
    edited_df = st.data_editor(
        df, 
        num_rows="dynamic", 
        key="data_editor", 
        width="stretch",
        column_config={
            "id": st.column_config.NumberColumn("ID", width="small", disabled=True),
            "project_name": st.column_config.TextColumn("Project", width="medium"),
            "start_time": st.column_config.DatetimeColumn("Start Time", width="medium"),
            "end_time": st.column_config.DatetimeColumn("End Time", width="medium"),
            "description": st.column_config.TextColumn("Description", width="large"),
            "is_active": st.column_config.CheckboxColumn("Active", width="small"),
            "duration_hours": st.column_config.NumberColumn("Hours", width="small", format="%.2f", disabled=True),
        },
        column_order=["project_name", "start_time", "end_time", "duration_hours", "description", "is_active", "id"],
    )
    
    if st.button("💾 Save Changes", type="primary", use_container_width=True):
        save_data(df, edited_df)
        st.success("Changes saved!")
        st.rerun()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB: Add Entry
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_add:
    st.caption("Quickly log past work without needing the menu bar app.")
    
    existing_projects = sorted(df['project_name'].dropna().unique().tolist()) if not df.empty else []
    
    with st.form("manual_entry_form", clear_on_submit=True):
        form_col1, form_col2 = st.columns(2)
        
        with form_col1:
            project_options = existing_projects + ["— Custom —"]
            selected_project = st.selectbox("Project", project_options, key="manual_project")
            entry_date = st.date_input("Date", value=datetime.date.today(), key="manual_date")
            description = st.text_input("Description", placeholder="What did you work on?", key="manual_desc")
        
        with form_col2:
            start_time_input = st.time_input("Start Time", value=datetime.time(9, 0), key="manual_start")
            end_time_input = st.time_input("End Time", value=datetime.time(17, 0), key="manual_end")
            
            if selected_project == "— Custom —":
                selected_project = st.text_input("Custom Project Name", key="manual_custom_project")
        
        # Compute preview values
        start_dt = datetime.datetime.combine(entry_date, start_time_input)
        end_dt = datetime.datetime.combine(entry_date, end_time_input)
        if end_dt <= start_dt:
            end_dt += datetime.timedelta(days=1)
        duration = (end_dt - start_dt).total_seconds() / 3600.0
        
        # Preview as a table row
        st.subheader("Preview")
        preview_data = pd.DataFrame([{
            "Project": selected_project or "—",
            "Date": entry_date.strftime("%b %d, %Y"),
            "Start": start_time_input.strftime("%I:%M %p"),
            "End": end_time_input.strftime("%I:%M %p"),
            "Hours": round(duration, 1),
            "Description": description or "—",
        }])
        st.dataframe(preview_data, use_container_width=True, hide_index=True)
        
        submitted = st.form_submit_button("➕ Add Entry", type="primary", use_container_width=True)
        
        if submitted:
            if not selected_project or not selected_project.strip():
                st.error("Please enter a project name.")
            else:
                conn = sqlite3.connect(DB_NAME)
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO time_logs (project_name, start_time, end_time, description, is_active)
                    VALUES (?, ?, ?, ?, 0)
                ''', (selected_project.strip(), start_dt.isoformat(), end_dt.isoformat(), description))
                conn.commit()
                conn.close()
                st.success(f"✅ Added {duration:.1f}h for '{selected_project}' on {entry_date.strftime('%b %d')}!")
                st.rerun()
    
    # Recent entries for context (outside the form)
    st.subheader("Recent Entries")
    if not df.empty:
        recent = df.dropna(subset=['start_time', 'end_time']).copy()
        recent = recent[recent['description'] != '[Paused]']
        recent = recent.sort_values('start_time', ascending=False).head(10)
        
        if not recent.empty:
            display_recent = recent[['project_name', 'start_time', 'end_time', 'duration_hours', 'description']].copy()
            display_recent.columns = ['Project', 'Start', 'End', 'Hours', 'Description']
            st.dataframe(display_recent, use_container_width=True, hide_index=True)
        else:
            st.caption("No entries yet.")
    else:
        st.caption("No entries yet.")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TAB: Export
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
with tab_export:
    if not df.empty:
        st.subheader("Configure Export")
        
        export_df = df.copy()
        
        # ── Filters ────────────────────────────────────────────────
        filter_col1, filter_col2 = st.columns(2)
        
        with filter_col1:
            # Date range filter
            local_tz = datetime.datetime.now().astimezone().tzinfo
            all_start_times = pd.to_datetime(export_df['start_time'], utc=True).dropna()
            
            if not all_start_times.empty:
                min_date = all_start_times.min().astimezone(local_tz).date()
                max_date = all_start_times.max().astimezone(local_tz).date()
            else:
                min_date = datetime.date.today() - datetime.timedelta(days=30)
                max_date = datetime.date.today()
            
            export_date_range = st.date_input(
                "Date Range",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date,
                key="export_date_range"
            )
            
            # Apply date filter
            if isinstance(export_date_range, tuple) and len(export_date_range) == 2:
                range_start = pd.Timestamp(export_date_range[0]).tz_localize(local_tz).tz_convert('UTC')
                range_end = (pd.Timestamp(export_date_range[1]) + pd.to_timedelta(1, unit='d')).tz_localize(local_tz).tz_convert('UTC')
                compare = pd.to_datetime(export_df['start_time'], utc=True)
                export_df = export_df[(compare >= range_start) & (compare < range_end)]
        
        with filter_col2:
            # Project filter
            all_projects = sorted(df['project_name'].dropna().unique().tolist())
            selected_projects = st.multiselect(
                "Projects",
                options=all_projects,
                default=all_projects,
                key="export_projects"
            )
            if selected_projects:
                export_df = export_df[export_df['project_name'].isin(selected_projects)]
        
        # ── Options ────────────────────────────────────────────────
        opt_col1, opt_col2 = st.columns(2)
        
        with opt_col1:
            exclude_paused = st.checkbox("Exclude paused entries", value=True, key="export_exclude_paused")
            if exclude_paused:
                export_df = export_df[export_df['description'] != '[Paused]']
                
            exclude_active = st.checkbox("Exclude active (unfinished) entries", value=True, key="export_exclude_active")
            if exclude_active:
                export_df = export_df[export_df['is_active'] != True]
        
        with opt_col2:
            # Column selector
            all_columns = ["project_name", "start_time", "end_time", "duration_hours", "description", "is_active", "id"]
            available_cols = [c for c in all_columns if c in export_df.columns]
            default_cols = [c for c in ["project_name", "start_time", "end_time", "duration_hours", "description"] if c in available_cols]
            
            selected_columns = st.multiselect(
                "Columns to include",
                options=available_cols,
                default=default_cols,
                key="export_columns"
            )
        
        if selected_columns:
            export_df = export_df[[c for c in selected_columns if c in export_df.columns]]
        
        st.divider()
        
        # ── Export Summary ─────────────────────────────────────────
        st.subheader("Export Preview")
        
        sum_col1, sum_col2, sum_col3 = st.columns(3)
        
        total_rows = len(export_df)
        sum_col1.metric("Rows to Export", total_rows)
        
        if 'duration_hours' in export_df.columns and not export_df['duration_hours'].isna().all():
            total_hrs = export_df['duration_hours'].sum()
            sum_col2.metric("Total Hours", f"{total_hrs:.1f}h")
        
        if 'project_name' in export_df.columns:
            num_projects = export_df['project_name'].nunique()
            sum_col3.metric("Projects", num_projects)
        
        # ── Full Preview Table ─────────────────────────────────────
        if not export_df.empty:
            st.dataframe(export_df, use_container_width=True, height=300)
            
            csv = export_df.to_csv(index=False).encode('utf-8')
            
            # Filename with date range
            if isinstance(export_date_range, tuple) and len(export_date_range) == 2:
                fname = f"timesheet_{export_date_range[0].isoformat()}_to_{export_date_range[1].isoformat()}.csv"
            else:
                fname = f"timesheet_{datetime.date.today().isoformat()}.csv"
            
            st.download_button(
                label="📥 Download CSV",
                data=csv,
                file_name=fname,
                mime='text/csv',
                type="primary",
                use_container_width=True,
            )
        else:
            st.info("No entries match your current filters. Adjust the filters above.", icon="📭")
    else:
        st.info("No data available to export.", icon="📭")

