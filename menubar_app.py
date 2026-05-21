import rumps
import subprocess
import db_logic
import os
import re
from datetime import datetime, timedelta

# Define path for our defaults file
PROJECTS_FILE = os.path.join(os.path.dirname(__file__), 'projects.txt')

def format_time(iso_string):
    if not iso_string:
        return "Unknown"
    try:
        dt = datetime.fromisoformat(iso_string)
        return dt.strftime("%I:%M %p")
    except Exception:
        return iso_string

def load_projects():
    # Create default file if it doesn't exist
    if not os.path.exists(PROJECTS_FILE):
        with open(PROJECTS_FILE, 'w') as f:
            f.write("Project A\nProject B\nAdmin\n")
            
    # Read the projects from the file
    with open(PROJECTS_FILE, 'r') as f:
        projects = [line.strip() for line in f if line.strip()]
        
    return projects if projects else ["Default Project"]

class TimeTrackerApp(rumps.App):
    def __init__(self):
        super(TimeTrackerApp, self).__init__("⏱️ Idle")
        self.paused_project = None
        # Restore pause state if the app was quit mid-pause
        paused = db_logic.get_paused_timer()
        if paused:
            self.paused_project = paused["project_name"]
        self.build_menu()
        # Auto-refresh title every 60 seconds to keep elapsed time current
        self.timer = rumps.Timer(self.tick, 60)
        self.timer.start()

    def tick(self, sender):
        self.update_ui_state()

    def build_menu(self):
        self.menu.clear()
        
        self.status_item = rumps.MenuItem("Status: Idle", callback=None)
        self.menu.add(self.status_item)
        self.menu.add(rumps.separator)
        
        # Load from our text file
        self.projects = load_projects()
        for proj in self.projects:
            self.menu.add(rumps.MenuItem(proj, callback=self.start_project_timer))
            
        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Start Custom Project...", callback=self.start_custom_project))
        self.menu.add(rumps.MenuItem("Edit Default Projects...", callback=self.edit_defaults))
        
        active = db_logic.get_active_timer()
        if active:
            self.menu.add(rumps.separator)
            self.menu.add(rumps.MenuItem("⏱️ Subtract 5 mins from Start", callback=lambda _: self.adjust_timer(5)))
            self.menu.add(rumps.MenuItem("⏱️ Subtract 15 mins from Start", callback=lambda _: self.adjust_timer(15)))
            self.menu.add(rumps.MenuItem("⏱️ Subtract 30 mins from Start", callback=lambda _: self.adjust_timer(30)))
            self.menu.add(rumps.MenuItem("⏱️ Custom Adjustment...", callback=self.custom_adjust_timer))

        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Reload Menu", callback=lambda _: self.build_menu()))
        
        self.menu.add(rumps.separator)
        self.pause_button = rumps.MenuItem("Pause Timer", callback=self.toggle_pause)
        self.menu.add(self.pause_button)

        self.stop_button = rumps.MenuItem("Stop Timer", callback=self.stop_project_timer)
        self.menu.add(self.stop_button)
        
        self.update_ui_state()

    def update_ui_state(self):
        # Handle Paused state locally
        if self.paused_project:
            self.title = f"⏸️ {self.paused_project}"
            self.status_item.title = "Status: Paused"
            self.pause_button.title = "Resume Timer"
            return

        # Handle Active or Idle states
        self.pause_button.title = "Pause Timer"
        active = db_logic.get_active_timer()
        if active:
            proj = active["project_name"]
            start_str = format_time(active["start_time"])
            # Show elapsed time in the menu bar
            try:
                start_dt = datetime.fromisoformat(active["start_time"])
                elapsed = datetime.now() - start_dt
                hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
                mins = remainder // 60
                self.title = f"⏱️ {proj} ({hours}h {mins}m)"
            except Exception:
                self.title = f"⏱️ {proj}"
            self.status_item.title = f"Started: {start_str}"
        else:
            self.title = "⏱️ Idle"
            last_ended = db_logic.get_last_ended_timer()
            if last_ended:
                end_str = format_time(last_ended["end_time"])
                self.status_item.title = f"Last ended: {end_str} ({last_ended['project_name']})"
            else:
                self.status_item.title = "Status: Idle"

    def start_project_timer(self, sender):
        project_name = sender.title
        self._start_timer_logic(project_name)

    def start_custom_project(self, sender):
        window = rumps.Window(
            message="Enter custom project name:",
            title="Custom Project",
            default_text="",
            cancel=True
        )
        response = window.run()
        if response.clicked and response.text.strip():
            self._start_timer_logic(response.text.strip())

    def edit_defaults(self, sender):
        # Open the text file in the user's default text editor (safe subprocess call)
        subprocess.run(["open", PROJECTS_FILE])
        rumps.alert(
            title="Edit Defaults",
            message="I've opened the projects.txt file for you.\n\nEdit the file, save it, and click OK here. Your menu will instantly update!"
        )
        self.build_menu()

    def toggle_pause(self, sender):
        if self.paused_project:
            # Resume by reopening the paused row so the original start_time is preserved
            self.paused_project = None
            db_logic.resume_paused_timer()
            self.build_menu()
        else:
            # Pause
            active = db_logic.get_active_timer()
            if not active:
                rumps.alert("No active timer to pause.")
                return

            self.paused_project = active["project_name"]
            # Silently stop timer in DB with a placeholder description
            db_logic.stop_timer("[Paused]")
            self.build_menu()

    def adjust_timer(self, mins):
        active = db_logic.get_active_timer()
        if not active:
            return
        dt = datetime.fromisoformat(active["start_time"])
        new_dt = dt - timedelta(minutes=mins)
        db_logic.set_active_start_time(new_dt.isoformat())
        self.build_menu()

    def custom_adjust_timer(self, sender):
        window = rumps.Window(
            message="Enter minutes to subtract (e.g. '45' or '15m') OR absolute start time (e.g. '10:30'):",
            title="Custom Adjustment",
            default_text="",
            cancel=True
        )
        resp = window.run()
        if not resp.clicked or not resp.text.strip():
            return
            
        val = resp.text.strip().lower()
        active = db_logic.get_active_timer()
        if not active: return
        
        start_time_dt = datetime.fromisoformat(active["start_time"])
        now = datetime.now()
        
        try:
            mins = int(val)
            start_time_dt -= timedelta(minutes=mins)
            db_logic.set_active_start_time(start_time_dt.isoformat())
            self.build_menu()
            return
        except ValueError:
            pass
            
        m_time = re.match(r'^(\d{1,2}):(\d{2})$', val)
        if m_time:
            hours = int(m_time.group(1))
            minutes = int(m_time.group(2))
            start_time_dt = start_time_dt.replace(hour=hours, minute=minutes, second=0, microsecond=0)
            if start_time_dt > now:
                start_time_dt -= timedelta(days=1)
            
            db_logic.set_active_start_time(start_time_dt.isoformat())
            self.build_menu()
            return
            
        m_mins = re.match(r'^(\d+)\s*m(?:ins?|inutes?)?$', val)
        if m_mins:
            mins = int(m_mins.group(1))
            start_time_dt -= timedelta(minutes=mins)
            db_logic.set_active_start_time(start_time_dt.isoformat())
            self.build_menu()
            return
            
        rumps.alert("Invalid Input", "Please enter a number of minutes (e.g. 45) or a time (e.g. 10:30).")

    def _start_timer_logic(self, project_name, start_time=None):
        self.paused_project = None # Clear any pause state
        active = db_logic.get_active_timer()
        if active:
            # Confirm before switching to a different project
            if active["project_name"] != project_name:
                resp = rumps.alert(
                    title="Timer Already Running",
                    message=f"'{active['project_name']}' is currently being tracked.\nSwitch to '{project_name}'?",
                    ok="Switch",
                    cancel="Cancel"
                )
                if resp != 1:  # User cancelled
                    return
            self.stop_project_timer(None, force=True)
            
        db_logic.start_timer(project_name, start_time)
        self.build_menu()

    def stop_project_timer(self, sender, force=False):
        was_paused = self.paused_project is not None
        self.paused_project = None # Clear pause state entirely
        
        if not db_logic.get_active_timer() and not was_paused:
            if not force:
                rumps.alert("No active timer to stop.")
            return

        window = rumps.Window(
            message="What did you just work on?",
            title="Stop Timer",
            default_text="",
            cancel=False
        )
        response = window.run()
        description = response.text
        
        if was_paused:
            # It was already paused (stopped) in the DB, so we just overwrite the '[Paused]' description
            db_logic.update_last_description(description)
        else:
            # Stop the active timer normally
            db_logic.stop_timer(description)
            
        self.build_menu()

if __name__ == "__main__":
    app = TimeTrackerApp()
    app.run()
