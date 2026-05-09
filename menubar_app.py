import rumps
import db_logic
import os
from datetime import datetime

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
        self.build_menu()

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
        # Open the text file in the user's default text editor
        os.system(f'open "{PROJECTS_FILE}"')
        rumps.alert(
            title="Edit Defaults",
            message="I've opened the projects.txt file for you.\n\nEdit the file, save it, and click OK here. Your menu will instantly update!"
        )
        self.build_menu()

    def toggle_pause(self, sender):
        if self.paused_project:
            # Resume
            project_to_resume = self.paused_project
            self.paused_project = None
            self._start_timer_logic(project_to_resume)
        else:
            # Pause
            active = db_logic.get_active_timer()
            if not active:
                rumps.alert("No active timer to pause.")
                return
            
            self.paused_project = active["project_name"]
            # Silently stop timer in DB with a placeholder description
            db_logic.stop_timer("[Paused]")
            self.update_ui_state()

    def _start_timer_logic(self, project_name):
        self.paused_project = None # Clear any pause state
        if db_logic.get_active_timer():
            self.stop_project_timer(None, force=True)
            
        db_logic.start_timer(project_name)
        self.update_ui_state()

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
            
        self.update_ui_state()

if __name__ == "__main__":
    app = TimeTrackerApp()
    app.run()
