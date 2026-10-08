# Local Time Tracker

A 100% local time-tracking application for macOS. This system allows you to easily track your work hours from the macOS menu bar and manage your timesheets via a local web dashboard. All data is securely stored locally in a SQLite database, ensuring privacy and immediate access.

## Quick Commands

Each block below is self-contained — copy the whole line and paste it into a fresh Terminal window. No need to `cd` first; the `cd` is already included.

**Open the dashboard** (then visit <http://localhost:8501>):
```bash
cd /Users/joewu/Batcave/Local-Time-Tracker && streamlit run timesheet_dashboard.py
```

**Stop the dashboard:** click inside that Terminal window and press `Control + C`.

**Open the desktop timer window** (use this when the menu bar is full or hidden behind the notch):
```bash
cd /Users/joewu/Batcave/Local-Time-Tracker && python3 timer_app.py
```

**Build it as a real Mac app** (proper name and icon in the Dock, then launch from Spotlight):
```bash
cd /Users/joewu/Batcave/Local-Time-Tracker && ./build_app.sh /Applications
```

**Start the menu bar app:**
```bash
cd /Users/joewu/Batcave/Local-Time-Tracker && python3 menubar_app.py
```

**Restart the menu bar app** (use this after pulling code changes — a running copy keeps the old code in memory):
```bash
pkill -f menubar_app.py; cd /Users/joewu/Batcave/Local-Time-Tracker && nohup python3 menubar_app.py > /dev/null 2>&1 &
```

**Generate last month's invoice:**
```bash
cd /Users/joewu/Batcave/Local-Time-Tracker && python3 generate_invoice.py
```

**Generate a specific month's invoice** (change the date):
```bash
cd /Users/joewu/Batcave/Local-Time-Tracker && python3 generate_invoice.py --month 2026-08
```

> **Note:** use `python3`, never `python` — this Mac has no `python` command, so anything starting with `python ` will fail with `command not found`.

## Architecture

The system is composed of five decoupled components running entirely on your local machine:

1. **Database & Logic Layer (`db_logic.py`)**
   * Uses a SQLite database (`time_tracker.db`) to store time logs.
   * Manages the core backend logic: starting timers, stopping timers (with descriptions), and fetching the active timer state.
   * Ensures data integrity and provides a solid foundation independent of the UI.

2. **macOS Menu Bar Application (`menubar_app.py`)**
   * Built using the Python `rumps` library.
   * Provides a lightweight data-entry interface directly in the macOS menu bar.
   * Displays "⏱️ Idle" or "⏱️ [Project Name]" based on the active timer.
   * Allows starting timers via preset project dropdowns and stopping timers with a prompt for a short task description.

3. **Desktop Timer Window (`timer_app.py`)**
   * A standalone `tkinter` window — an alternative to the menu bar for when the menu bar is full or items are hidden behind the MacBook Pro's notch.
   * Live elapsed-time readout, Start / Pause / Stop, manual hour logging, and today/this-week totals.
   * Optional **Always on top** so it floats over every app, Space, and display.
   * Pure Python standard library — no extra packages. Reads and writes the same database, so it stays in sync with the menu bar app and dashboard automatically.

4. **Local Web Dashboard (`timesheet_dashboard.py`)**
   * Built using `streamlit` and `pandas`.
   * Serves as the "back office" to view, edit, aggregate, and export timesheet data.
   * **Features:**
     * Interactive data editor (`st.data_editor`) to correct timestamps or descriptions (writes changes back to the database), with click-to-sort column headers and an All Time / Month / Custom Range date filter.
     * Long-form description editor for multi-line notes that the single-line grid cells can't handle.
     * Summary section displaying total duration hours grouped by project via bar charts, with an optional estimated-revenue readout driven by an hourly rate.
     * Export functionality to download the timesheet view as a CSV file for final submission.

5. **Invoice Generator (`generate_invoice.py`)**
   * CLI script that turns a month of time logs into a filled-in copy of the Mehaffey Consulting billing template.
   * Groups entries by day + project + auto-classified item code (`Meeting` / `Drafting` / `Research`), sums hours (rounded to the nearest 0.25), and joins descriptions.
   * Preserves the template's rate, GST, and total formulas — outputs to `./invoices/` for review before sending.

## Prerequisites

* macOS
* Python 3.x — invoked as `python3`. There is **no** `python` command on this Mac.
* Required Python libraries:
  ```bash
  python3 -m pip install rumps streamlit pandas openpyxl
  ```

Verify the tools are on your `PATH` (both should print a path, not "not found"):
```bash
which python3 streamlit
```
If `streamlit` isn't found, call it through Python instead — substitute `python3 -m streamlit run ...` for `streamlit run ...` in every command below.

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

**What's in the menu:**
* **Project names** — click one to start a timer. **Start Custom Project…** for anything not in your presets.
* **➕ Log Hours Manually** — records time you've already worked without running a timer. Pick a project, type the hours (e.g. `5.5`), add an optional description. The entry is saved ending at the current time, and won't disturb a timer that's already running.
* **⏱️ Custom Adjustment…** (only shown while a timer is running) — moves the start time backwards. Accepts:
  * minutes: `45`, `15m`, `15mins`
  * hours: `2h`, `1.5h`, `2hours`
  * an absolute start time: `10:30`
* **Pause / Stop Timer** — stopping prompts you for a description of what you worked on.

**After pulling code changes**, quit and relaunch the app. A running copy holds the old code in memory, so fixes won't take effect until it restarts:
```bash
pkill -f menubar_app.py; cd /Users/joewu/Batcave/Local-Time-Tracker && nohup python3 menubar_app.py > /dev/null 2>&1 &
```

To run it in the foreground instead (useful for seeing errors while debugging):
```bash
cd /Users/joewu/Batcave/Local-Time-Tracker && python3 menubar_app.py
```

### 2. The Desktop Timer Window (`timer_app.py`)
A standalone window for when the menu bar isn't usable — on a MacBook Pro the notch hides overflowing menu bar items entirely, and a menu bar manager like Hidden Bar can tuck the tracker away too. This window doesn't depend on menu bar space at all.

**Run it:**
```bash
cd /Users/joewu/Batcave/Local-Time-Tracker && python3 timer_app.py
```

**It resizes between two layouts.** Drag the window short and it collapses to a one-line bar — clock, project, Pause/Stop — small enough to park in a screen corner with *Always on top*. Pull it tall and it expands to the full panel. It's one window with a size breakpoint, not two modes to switch between, and it reopens at whatever size you left it.

Two ways to switch:
* **Drag the bottom edge.** It collapses below 250px and expands above 290px, swapping as you drag. The gap between those two numbers is deliberate — it stops the layout flickering when you hover right on the boundary. Expanded, the window is capped at the height of its content, so you won't find empty space under the footer.
* **Double-click the window background** (or the clock, or the totals) to snap straight between the two. It remembers your tall height, so toggling back restores the size you had.

**What's in the window:**
* Big live elapsed-time readout plus the current project and start time.
* **Start Timer** when idle — pick a preset from the dropdown or type any project name.
* **Pause / Resume** and **Stop** (see the stop dialog below).
* **Adjust start** — pulls a running timer's start time backwards, for when you began working before you remembered to hit start. Quick −5 / −15 / −30 buttons, or type the same forms the menu bar app accepts: `45`, `15m`, `2h`, `1.5h`, or a time like `10:30`.
* **Discard** — deletes a timer started by mistake without logging anything. Asks first, and names the project and elapsed time so you know what you're throwing away.
* **➕ Log Hours Manually** — project, hours (e.g. `5.5`), and an optional description, saved ending now.
* **Today** and **This Week** running totals.
* **Always on top** — the window floats above other apps' windows. Remembered between launches. Note it won't follow you to another macOS *Space*; Tk doesn't expose that setting.

It polls the database once a second, so timers started from the menu bar app show up here (and vice versa) without a manual refresh. Any save failure raises a visible error dialog rather than failing silently.

**The stop dialog.** Stopping opens a window that does three things:

1. **Shows what will be logged** — the raw session length, and separately the day's running total for that project with the invoice's round-up applied:
   ```
   This session     2:15:30        2.25 h
   LRTM today       3.75 h    →    3.8 h billable
   ```
   These are two numbers on purpose. `generate_invoice.py` rounds up the **daily bucket**, not each session, so a per-session figure would over-bill. The app imports the rounding rule and `classify()` from the invoice script so the two can't drift apart.
2. **Lets you correct the entry** before saving — hit **Adjust** to edit the start, the end, the duration, or the **project**; everything else recalculates live, including the billable figure, which changes when you switch project. The time editing exists because several entries in the database carry corrections written into the notes instead ("Adjust to 2 hr 15 min for total session").
3. **Takes multi-line notes.** The invoice derives the item code (Meeting / Drafting / Research) from keywords in what you write, so the code isn't shown or second-guessed here — it follows the text.

Closing the dialog with notes typed asks before discarding them, and quitting the app with a timer still going offers to leave it running, stop and save it, or discard it.

**Make it a real Mac app (one-time):**
```bash
cd /Users/joewu/Batcave/Local-Time-Tracker && ./build_app.sh /Applications
```
This builds `Time Tracker.app` — proper name and icon in the Dock and menu bar instead of "Python" — using only macOS's own `sips`/`iconutil`, nothing to install. Launch it from Spotlight (`⌘Space` → "Time Tracker"), the Dock, or Launchpad.

Omit the argument to build into `./dist` instead. The bundle points back at this folder, so edits to `timer_app.py` take effect immediately — only rebuild if you move the project or change Python.

See [DESIGN.md](DESIGN.md) for why the window is laid out the way it is, the options that were considered, and the billing-accuracy finding behind the stop dialog.

### 3. The Dashboard (On-Demand Viewer)
The Streamlit dashboard acts as your "back office." You only need to run this when you want to view, edit, or export your timesheets.

1. Open a new Terminal window and paste this single line:
   ```bash
   cd /Users/joewu/Batcave/Local-Time-Tracker && streamlit run timesheet_dashboard.py
   ```
   The `cd` is bundled in deliberately — pasting `streamlit run timesheet_dashboard.py` on its own fails with `File does not exist`, because a fresh Terminal starts in your home folder, not the project folder.
2. A browser window opens automatically at <http://localhost:8501>. If it doesn't, open that address yourself.
3. Using the **📋 Time Logs** tab:
   * **Filtering:** Pick `All Time`, `Month`, or `Custom Range` at the top. The caption underneath shows how many entries and hours are in view.
   * **Sorting:** Click any column header (Start Time, End Time, Hours…) to sort. Rows default to oldest-first.
   * **Editing:** Double-click any cell to correct typos, descriptions, or project names.
   * **Long descriptions:** Grid cells are single-line and close the moment you press Enter. For multi-line notes, scroll to **✏️ Edit Description (long-form)** below the table, pick the entry, type freely, and click **💾 Save Description**. Hit **🔄 Reload** there if you changed a description somewhere else and want the box re-read from the database.
   * **Deleting:** Highlight a row and press `Delete`.
   * **Adding:** New entries go in the **➕ Add Entry** tab, not the grid. (Streamlit turns off column sorting whenever grid row-adding is enabled, so the grid trades adding for sorting.)
   * **Saving (Crucial):** Table edits are NOT permanent until you click **💾 Save Changes** below the table. Deletions and cell edits apply only to the rows currently in view, so filtering is safe.
4. **Estimated revenue:** Open the sidebar and tick **Show estimated revenue**, then set your hourly rate. Revenue figures appear on the top cards and in the Summary tab, scaled to whichever period you've filtered to. It's off by default.
5. **To Quit:** Click inside your Terminal window and press `Control + C` to shut down the server.
   If you closed that window and the server is still running, free the port with:
   ```bash
   pkill -f "streamlit run timesheet_dashboard.py"
   ```

### 4. Generating a Monthly Invoice (`generate_invoice.py`)
Run this once a month to produce a filled-in copy of the Mehaffey Consulting billing template.

**One-time setup:**
The template path is hardcoded near the top of `generate_invoice.py`:
```python
TEMPLATE_PATH = Path("/Users/.../Mehaffy Billing Template.xlsx")
```
Edit that constant if the OneDrive path ever changes. Optionally edit `EXCLUDE_PROJECTS` to skip projects you don't want billed (e.g. `["Personal Projects"]`).

**Run it:**
1. Open a new Terminal window and paste one of these single lines.
2. For the previous calendar month (the usual case):
   ```bash
   cd /Users/joewu/Batcave/Local-Time-Tracker && python3 generate_invoice.py
   ```
   …or specify a month explicitly (change `2026-08` to the month you want):
   ```bash
   cd /Users/joewu/Batcave/Local-Time-Tracker && python3 generate_invoice.py --month 2026-08
   ```
3. The script prints the output path and a summary (line item count, total hours). The file lands in `./invoices/Mehaffey Invoice INV-YYYY-MM.xlsx` (this folder is gitignored). It also mirrors a copy to the OneDrive Invoices folder using its own naming convention (`Joe - Mehaffey Invoice MMYYYY.xlsx`). Set `ONEDRIVE_INVOICES_DIR = None` in the script to skip the mirror; passing `--out` also skips it.
4. **Open the file in Excel and review** — the script auto-classifies each row's Item code from keywords in the description (`meeting` → Meeting, `draft`/`document` → Drafting, else Research). Eyeball each row, adjust anything wrong, then send.

**Other flags:**
* `--month last` — explicit form of the default (previous month)
* `--out /some/path.xlsx` — override the output location

### 5. Customizing Projects
You can customize the preset projects directly from the menu bar app by clicking **"Edit Default Projects..."**. This will open a text file where you can add or remove presets. Once saved, click "OK" on the alert prompt, and your menu will instantly refresh!
