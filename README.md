# Local Time Tracker

A 100% local time-tracking application for macOS. This system allows you to easily track your work hours from the macOS menu bar and manage your timesheets via a local web dashboard. All data is securely stored locally in a SQLite database, ensuring privacy and immediate access.

## Architecture

The system is composed of three decoupled components running entirely on your local machine:

1. **Database & Logic Layer (`db_logic.py`)**
   * Uses a SQLite database (`time_tracker.db`) to store time logs.
   * Manages the core backend logic: starting timers, stopping timers (with descriptions), and fetching the active timer state.
   * Ensures data integrity and provides a solid foundation independent of the UI.

2. **macOS Menu Bar Application (`menubar_app.py`)**
   * Built using the Python `rumps` library.
   * Provides a lightweight data-entry interface directly in the macOS menu bar.
   * Displays "⏱️ Idle" or "⏱️ [Project Name]" based on the active timer.
   * Allows starting timers via preset project dropdowns and stopping timers with a prompt for a short task description.

3. **Local Web Dashboard (`timesheet_dashboard.py`)**
   * Built using `streamlit` and `pandas`.
   * Serves as the "back office" to view, edit, aggregate, and export timesheet data.
   * **Features:**
     * Interactive data editor (`st.data_editor`) to correct timestamps or descriptions (writes changes back to the database).
     * Summary section displaying total duration hours grouped by project via bar charts.
     * Export functionality to download the timesheet view as a CSV or Parquet file for final submission.

## Prerequisites

* macOS
* Python 3.x
* Required Python libraries:
  ```bash
  pip install rumps streamlit pandas
  ```

## Usage

### 1. The Menu Bar App (Background Tracker)
The menu bar app is designed to run silently in the background while you work, without tying up a terminal window.

**Setup Instructions (One-time):**
1. Open the **Automator** app on your Mac.
2. Click **New Document** and choose **Application**.
3. Add a **"Run Shell Script"** action.
4. Paste the following code into the box:
   ```bash
   cd /Users/joewu/Batcave/Local-Time-Tracker
   /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 menubar_app.py > /dev/null 2>&1 &
   ```
5. Save the Automator file to your `Applications` folder as **"Time Tracker"**.
   *(Optional: You can customize the icon by pasting `icon.png` into the app's "Get Info" properties!)*

**Daily Use:**
Simply double-click your new "Time Tracker" app. The `⏱️ Idle` icon will quietly appear in your top menu bar.

### 2. The Dashboard (On-Demand Viewer)
The Streamlit dashboard acts as your "back office." You only need to run this when you want to view, edit, or export your timesheets.

1. Open your terminal and navigate to the project folder.
2. Run the dashboard:
   ```bash
   streamlit run timesheet_dashboard.py
   ```
3. A browser window will automatically open with your timesheets. 
   * **Editing:** Double-click any cell in the table to correct typos, descriptions, or project names.
   * **Adding/Deleting:** Click the faded bottom row to manually add missing time logs, or highlight a row and press `Delete` to remove it.
   * **Saving (Crucial):** Your edits are NOT permanent until you click the **"Save Changes to Database"** button below the table!
4. **To Quit:** Once you are done reviewing your data, click inside your terminal and press `Control + C` to shut down the server.

### 3. Customizing Projects
You can customize the preset projects directly from the menu bar app by clicking **"Edit Default Projects..."**. This will open a text file where you can add or remove presets. Once saved, click "OK" on the alert prompt, and your menu will instantly refresh!
