#!/usr/bin/env python3
"""Standalone desktop timer window for Local Time Tracker.

A clickable alternative to the menu bar app, for when the menu bar is full or
hidden behind the notch. Reads and writes the same SQLite database, so it stays
in sync with menubar_app.py and the Streamlit dashboard automatically.

The window is responsive: drag it short and it collapses to a one-line bar;
pull it tall and it expands to the full panel. See DESIGN.md for the design
rationale and the options that were considered.

Run it with:
    python3 timer_app.py
"""

import datetime
import json
import math
import os
import re
import tkinter as tk
from tkinter import font as tkfont

import db_logic

# Billing rules are imported, never reimplemented, so the figures shown here
# cannot drift away from what generate_invoice.py actually puts on the invoice.
from generate_invoice import (EXCLUDE_PROJECTS, SPILLOVER_THRESHOLD_HOURS,
                              classify, split_by_calendar_day)

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECTS_FILE = os.path.join(HERE, 'projects.txt')
SETTINGS_FILE = os.path.join(HERE, '.timer_app_settings.json')

POLL_MS = 1000       # re-read the DB every second so external changes show up

# Layout swapping uses a hysteresis band rather than a timed debounce: collapse
# below COLLAPSE_BELOW, expand above EXPAND_ABOVE, and hold whatever you have
# in between. Swapping on the spot keeps a drag feeling live — a debounce left
# the old layout squashed and clipped until the mouse was released — while the
# dead zone stops it flickering when you hover right on the boundary.
COLLAPSE_BELOW = 250
EXPAND_ABOVE = 290
BREAKPOINT_H = 260   # single threshold, used only to pick the opening layout
COMPACT_HEIGHT = 158
SETTLE_MS = 360
# One button height and one label size everywhere. Mixing 50/42/36 made rows
# that sit directly above each other look misaligned.
BTN_H = 46
BTN_SIZE = 14
FIELD_H = 44      # text inputs and the project picker
FIELD_SIZE = 15

# Corner rendering. Tk antialiases a splined curve but not a raw polygon fill,
# so these stay splines; SPLINE_STEPS subdivides the same curve more finely,
# which is the part that can be tuned without losing the antialiasing.
# Drop RADIUS toward 4 for crisper corners on a 1x external monitor, or raise
# it toward 10 for softer ones on a Retina panel.
RADIUS = 7
SPLINE_STEPS = 24
# Back to roughly the original window: the compact bar needs 363px of width,
# so 380 clears it with margin. The height auto-fits the content anyway.
MIN_W, DEFAULT_W, MAX_W = 372, 380, 560
DEFAULT_GEOMETRY = f"{DEFAULT_W}x500"
DEFAULT_HEIGHT = 500
# A single session longer than a day is a typo, not a work session. Bounding it
# also keeps datetime arithmetic away from OverflowError on a mistyped figure.
MAX_SESSION_HOURS = 24

# ── Design tokens ───────────────────────────────────────────────────
T = {
    "bg":       "#ffffff",
    "surface":  "#f6f7f9",
    "border":   "#e4e6eb",
    "border2":  "#d7dae1",
    "text":     "#15181f",
    "muted":    "#3f4554",
    # The dimmed 0:00:00 shown when nothing is running. It has to read as
    # inactive without becoming invisible: #9ba2af managed only 2.57:1, which
    # fails even the 3:1 allowed for large text.
    "ghost":    "#848d9e",
    "accent":   "#4453c4",
    "running":  "#0e8a5f",
    "runlabel": "#0b6e4c",
    "paused":   "#c77a00",
    "pauselbl": "#8a5a00",
    "idle":     "#7a8192",
    "danger":   "#c02626",
    "shadow":   "#d2d6de",
    "track":    "#bfc5d0",   # always-on-top switch, off
    "trackrim": "#9aa2b1",
    "knob":     "#ffffff",
    "knobedge": "#e8eaef",
    "knobcast": "#c9ced8",
}

# Semantic button fills. Darker than the matching status-dot colours, which are
# too light to carry white text at 4.5:1. Red is reserved for Discard: Stop
# *saves* the entry, and colouring it as a hazard would be a lie you'd learn to
# hesitate over twenty times a day.
TONES = {
    "go":     ("#0e7a55", "#ffffff"),   # start / resume      white 5.34:1
    "hold":   ("#a06400", "#ffffff"),   # pause               white 4.86:1
    "finish": ("#4453c4", "#ffffff"),   # stop and save       white 6.40:1
    "danger": ("#c02626", "#ffffff"),   # discard             white 5.92:1
    "neutral": ("#e3e7ee", "#15181f"),  # cancel / back out   ink  12.4:1
}
# All four carry white text, which means the amber has to be darker than a
# "true" amber: white needs 4.5:1, and #c07d0a reached only 3.40:1. #a06400 is
# the most saturated amber that still clears it, at 4.86:1.

UI = "Helvetica Neue"
MONO = "Menlo"
PAD = 24


def set_mac_app_name(name="Time Tracker"):
    """Rename the macOS application menu from "Python".

    The framework Python re-execs through its own Python.app bundle so it can
    be a GUI app, and AppKit reads the menu bar name from *that* bundle's
    Info.plist (CFBundleName = Python) — not from the .app wrapper the user
    launched. The wrapper fixes the Dock icon and name; only patching the
    bundle's info dictionary fixes the menu bar, and it has to happen before
    Tk initialises its menus.

    Silently does nothing off macOS or without PyObjC, which only costs the
    cosmetic rename.
    """
    try:
        from Foundation import NSBundle
    except ImportError:
        return
    bundle = NSBundle.mainBundle()
    if bundle is None:
        return
    info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
    if info is not None:
        try:
            info['CFBundleName'] = name
        except (TypeError, AttributeError):
            pass  # immutable on some builds — not worth failing over


def shade(hex_color, factor):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    r, g, b = (max(0, min(255, int(c * factor))) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def rounded_points(x1, y1, x2, y2, r):
    """Control polygon for a rounded rect, drawn with smooth=True.

    Tracing real arcs and drawing them unsmoothed is geometrically exact and
    looks worse: Tk's canvas antialiases a splined curve but not a raw polygon
    fill, so the "accurate" version renders with hard stair-stepped edges.
    Keep the spline.
    """
    return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2,
            x1 + r, y2, x1, y2, x1, y2 - r,
            x1, y1 + r, x1, y1]


def billable(hours):
    """Round up to the next 0.1 h — the rule generate_invoice.py applies."""
    return math.ceil(hours * 10) / 10


# ── Custom widgets ──────────────────────────────────────────────────
# macOS ignores background colours on native tk/ttk buttons, so the controls
# below are drawn on canvases to get a consistent, themeable look.
class Button(tk.Canvas):
    def __init__(self, parent, text, command, kind="secondary", height=BTN_H, size=BTN_SIZE,
                 shadow=False, tone=None):
        self.kind = "primary" if tone else kind
        self.shadow = shadow and self.kind != "ghost"
        if tone:
            self.fill, self.fg = TONES[tone]
            self.outline = self.fill
        elif kind == "primary":
            self.fill, self.fg, self.outline = T["accent"], "#ffffff", T["accent"]
        elif kind == "ghost":
            self.fill, self.fg, self.outline = parent["bg"], T["muted"], None
        else:
            self.fill, self.fg, self.outline = T["bg"], T["text"], T["border2"]
        super().__init__(parent, height=height, highlightthickness=0, bd=0,
                         bg=parent["bg"], cursor="pointinghand")
        self.text = text
        self.command = command
        self.font = tkfont.Font(family=UI, size=size, weight="bold")
        self._fill = self.fill
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Enter>", self._hover_on)
        self.bind("<Leave>", self._hover_off)
        self.bind("<Button-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1:
            return
        bottom = h - 1
        if self.shadow:
            # A soft drop shadow: one offset rounded rect behind the face.
            # Tk has no real blur, so the face is lifted 3px to leave it room.
            tint = shade(self.fill, 0.72) if self.kind == "primary" else T["shadow"]
            self.create_polygon(rounded_points(2, 4, w - 2, h - 1, RADIUS), smooth=True,
                                splinesteps=SPLINE_STEPS, fill=tint, outline=tint)
            bottom = h - 4
        if self.kind != "ghost":
            self.create_polygon(rounded_points(1, 1, w - 1, bottom, RADIUS), smooth=True,
                                splinesteps=SPLINE_STEPS, fill=self._fill,
                                outline=self.outline or self._fill)
        self.create_text(w / 2, (1 + bottom) / 2 + 1, text=self.text,
                         fill=self.fg, font=self.font)

    def _hover_on(self, _e):
        self._fill = shade(self.fill, 0.94) if self.kind == "primary" else T["surface"]
        if self.kind == "ghost":
            self.fg = T["text"]
        self._draw()

    def _hover_off(self, _e):
        self._fill = self.fill
        if self.kind == "ghost":
            self.fg = T["muted"]
        self._draw()

    def _press(self, _e):
        self._fill = shade(self.fill, 0.88) if self.kind == "primary" else T["border"]
        self._draw()

    def _release(self, _e):
        self._hover_on(_e)
        if self.command:
            self.command()

    def set_text(self, text):
        self.text = text
        self._draw()

    def set_tone(self, tone):
        """Recolour in place — Pause and Resume are different actions."""
        self.fill, self.fg = TONES[tone]
        self.outline = self._fill = self.fill
        self._draw()


class Toggle(tk.Canvas):
    W, H = 40, 23

    def __init__(self, parent, value=False, command=None):
        super().__init__(parent, width=self.W, height=self.H, highlightthickness=0,
                         bd=0, bg=parent["bg"], cursor="pointinghand")
        self.value = bool(value)
        self.command = command
        self.bind("<Button-1>", self._click)
        self._draw()

    def _draw(self):
        self.delete("all")
        radius = (self.H - 2) / 2
        # The off state was near-white on a white window and easy to miss, so
        # the track is darker with a rim, and the knob carries a shadow.
        track = T["accent"] if self.value else T["track"]
        rim = shade(T["accent"], 0.82) if self.value else T["trackrim"]
        self.create_polygon(rounded_points(2, 3, self.W - 1, self.H - 1, radius),
                            smooth=True, splinesteps=SPLINE_STEPS,
                            fill=T["shadow"], outline=T["shadow"])
        self.create_polygon(rounded_points(1, 1, self.W - 2, self.H - 3, radius),
                            smooth=True, splinesteps=SPLINE_STEPS,
                            fill=track, outline=rim)
        r = (self.H - 10) / 2
        cx = (self.W - 7 - r) if self.value else (6 + r)
        cy = (self.H - 2) / 2
        self.create_oval(cx - r, cy - r + 1, cx + r, cy + r + 1,
                         fill=T["knobcast"], outline="")      # knob shadow
        self.create_oval(cx - r, cy - r, cx + r, cy + r,
                         fill=T["knob"], outline=T["knobedge"])

    def _click(self, _e):
        self.value = not self.value
        self._draw()
        if self.command:
            self.command(self.value)


class Dropdown(tk.Toplevel):
    """A styled list that opens directly beneath its field.

    Tk's own tk_popup renders the native macOS context menu: it can't be
    themed and it positions itself at the pointer, so it never lines up with
    the field. This is a borderless Toplevel pinned to the field's left edge
    and width instead.
    """

    def __init__(self, anchor, items, on_pick, max_rows=8):
        super().__init__(anchor.winfo_toplevel())
        self.on_pick = on_pick
        # Taking the grab below steals it from a modal parent; remember who had
        # it so closing can hand it back, or that dialog silently stops being
        # modal and the window behind it becomes clickable again.
        self._prev_grab = anchor.winfo_toplevel().grab_current()
        # Hide while building. A Toplevel is mapped as soon as it exists, so
        # without this macOS first places it at its own default spot — which is
        # where it stays visible, to the side of the field it belongs under.
        self.withdraw()
        self.overrideredirect(True)
        self.configure(bg=T["border2"])

        body = tk.Frame(self, bg=T["bg"])
        body.pack(fill="both", expand=True, padx=1, pady=1)

        shown = items[:max_rows]
        for value in shown:
            # 15px/13px-inset matches the field's own text, so the list lines
            # up under what it replaces instead of reading as a separate thing.
            row = tk.Label(body, text=value, bg=T["bg"], fg=T["text"], font=(UI, 15),
                           anchor="w", padx=13, cursor="pointinghand")
            row.pack(fill="x", ipady=7)
            row.bind("<Enter>", lambda _e, w=row: w.config(bg=T["surface"]))
            row.bind("<Leave>", lambda _e, w=row: w.config(bg=T["bg"]))
            row.bind("<Button-1>", lambda _e, v=value: self._pick(v))

        anchor.update_idletasks()
        self.update_idletasks()
        w = max(anchor.winfo_width(), 160)
        h = self.winfo_reqheight()
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height() + 4

        # Keep the panel on screen if the field sits near the bottom edge.
        if y + h > self.winfo_screenheight() - 8:
            y = max(anchor.winfo_rooty() - h - 4, 8)

        self.geometry(f"{w}x{h}+{x}+{y}")
        self.deiconify()          # place first, then show
        self.attributes('-topmost', True)
        self.lift()

        self.bind("<Escape>", lambda _e: self.close())
        self.bind("<Button-1>", self._outside, add="+")
        self.grab_set()
        # An overrideredirect window is not given focus by the window manager,
        # so without this the Escape binding never receives a key event.
        self.focus_force()

    def _pick(self, value):
        self.on_pick(value)
        self.close()

    def _outside(self, event):
        # While grabbed, a click anywhere else is delivered here with
        # coordinates outside our bounds — treat that as dismiss.
        if event.widget is self and not (
                0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()):
            self.close()

    def close(self):
        try:
            self.grab_release()
        except tk.TclError:
            pass
        prev = self._prev_grab
        self.destroy()
        if prev is not None and str(prev):
            try:
                if prev.winfo_exists():
                    prev.grab_set()
            except tk.TclError:
                pass


class ProjectPicker(tk.Frame):
    """Bordered text field with a dropdown — type a new project or pick a preset."""

    def __init__(self, parent, projects, height=FIELD_H, size=FIELD_SIZE):
        super().__init__(parent, bg=T["bg"], highlightthickness=1,
                         highlightbackground=T["border2"], height=height)
        self.pack_propagate(False)
        self.projects = list(projects)
        self._menu = None
        self.var = tk.StringVar(value=projects[0] if projects else "")
        self.entry = tk.Entry(self, textvariable=self.var, bd=0, relief="flat",
                              bg=T["bg"], fg=T["text"], highlightthickness=0,
                              font=(UI, size, "bold"), insertbackground=T["text"])
        self.entry.pack(side="left", fill="both", expand=True, padx=(13, 0))
        self.caret = tk.Label(self, text="⌄", bg=T["bg"], fg=T["muted"],
                              font=(UI, 16), cursor="pointinghand")
        self.caret.pack(side="right", padx=(0, 13))
        self.caret.bind("<Button-1>", lambda _e: self.open())

    def open(self):
        if self._menu is not None and self._menu.winfo_exists():
            self._menu.close()
            self._menu = None
            return
        if not self.projects:
            return
        self._menu = Dropdown(self, self.projects, self.var.set)

    def get(self):
        return self.var.get().strip()


# ── Data helpers ────────────────────────────────────────────────────
def load_projects():
    if not os.path.exists(PROJECTS_FILE):
        return ["Default Project"]
    with open(PROJECTS_FILE, 'r') as f:
        projects = [line.strip() for line in f if line.strip()]
    return projects or ["Default Project"]


def load_settings():
    try:
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(data):
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(data, f)
    except Exception:
        pass  # a settings write failure should never break the app


def sane_geometry(spec):
    """Clamp a remembered geometry back into a usable range.

    A window that was zoomed before this was capped saved its stretched size,
    and restoring that verbatim reopened the app across the whole screen.
    Width is clamped and the position kept; the height is re-fitted on open.
    """
    if not spec:
        return DEFAULT_GEOMETRY
    m = re.match(r'^(\d+)x(\d+)([+-]\d+[+-]\d+)?$', spec.strip())
    if not m:
        return DEFAULT_GEOMETRY
    w = max(MIN_W, min(int(m.group(1)), MAX_W))
    h = max(118, int(m.group(2)))
    return f"{w}x{h}{m.group(3) or ''}"


def paused_row():
    """Full paused row (project, start, end) or None."""
    with db_logic.get_db() as (conn, cursor):
        cursor.execute('''
            SELECT project_name, start_time, end_time FROM time_logs
            WHERE id = (SELECT MAX(id) FROM time_logs)
              AND is_active = 0 AND description = '[Paused]'
        ''')
        row = cursor.fetchone()
    return None if not row else {"project_name": row[0], "start_time": row[1],
                                 "end_time": row[2]}


def _completed_rows():
    with db_logic.get_db() as (conn, cursor):
        cursor.execute('''
            SELECT project_name, start_time, end_time, description FROM time_logs
            WHERE end_time IS NOT NULL AND start_time IS NOT NULL AND is_active = 0
              AND (description IS NULL OR description != '[Paused]')
        ''')
        return cursor.fetchall()


def period_totals():
    """(today_hours, week_hours) across completed, non-paused entries."""
    now = datetime.datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - datetime.timedelta(days=today_start.weekday())
    today_h = week_h = 0.0
    for _proj, s, e, _d in _completed_rows():
        try:
            start = datetime.datetime.fromisoformat(s)
            hours = (datetime.datetime.fromisoformat(e) - start).total_seconds() / 3600.0
        except (TypeError, ValueError):
            continue
        if hours <= 0:
            continue
        if start >= week_start:
            week_h += hours
        if start >= today_start:
            today_h += hours
    return today_h, week_h


def day_shares(start, end):
    """[(day, hours)] for one session, the way the invoice apportions it.

    A session running past midnight is billed across both calendar days, except
    that a spillover shorter than the threshold folds back into the start day
    rather than becoming a tiny line of its own. Attributing the whole session
    to its start date instead would misstate every overnight session.
    """
    chunks = list(split_by_calendar_day(start, end))
    if not chunks:
        return []
    primary = chunks[0][0]
    shares = {}
    for i, (day, hours) in enumerate(chunks):
        target = primary if (i > 0 and hours < SPILLOVER_THRESHOLD_HOURS) else day
        shares[target] = shares.get(target, 0.0) + hours
    return sorted(shares.items())


def session_share(start, end, day):
    """Hours of one session that the invoice would bill on `day`."""
    return next((h for d, h in day_shares(start, end) if d == day), 0.0)


def day_bucket(project, day, item_code=None):
    """Raw hours already logged for (day, project) — optionally one item code.

    Mirrors generate_invoice.aggregate_by_day's bucket key, which is what the
    0.1 h round-up is applied to. Rounding a single session instead would
    over-bill, because every session would get its own ceiling.
    """
    total = 0.0
    codes = set()
    for proj, s, e, desc in _completed_rows():
        if proj != project:
            continue
        try:
            start = datetime.datetime.fromisoformat(s)
            end = datetime.datetime.fromisoformat(e)
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        share = session_share(start, end, day)
        if share <= 0:
            continue
        code = classify(desc or "")
        codes.add(code)
        if item_code is None or code == item_code:
            total += share
    return total, codes


def bind_double_click(widget, command):
    """Bind a double-click across a view's inert surfaces.

    Frames and plain labels only: binding the canvas buttons would fire the
    toggle on a quick double press of Stop, and binding entry fields would
    break double-click-to-select-a-word.
    """
    if isinstance(widget, (tk.Frame, tk.Label)):
        widget.bind("<Double-Button-1>", lambda _e: command(), add="+")
    for child in widget.winfo_children():
        if isinstance(child, (tk.Entry, tk.Text, tk.Canvas)):
            continue
        bind_double_click(child, command)


def fmt_elapsed(delta):
    total = max(int(delta.total_seconds()), 0)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def parse_adjustment(text, current_start, now=None):
    """New start time from an adjustment, using the menu bar app's grammar.

    Accepts minutes to subtract (``45``, ``15m``, ``15mins``), hours
    (``2h``, ``1.5h``, ``2hours``) or an absolute clock time (``10:30``),
    so the two apps behave the same way. Raises ValueError on anything else.
    """
    now = now or datetime.datetime.now()
    val = (text or "").strip().lower()
    if not val:
        raise ValueError("Enter an amount to subtract, or a start time.")

    m = re.match(r'^(\d+(?:\.\d+)?)\s*h(?:ours?|rs?)?$', val)
    if m:
        return current_start - datetime.timedelta(hours=float(m.group(1)))

    m = re.match(r'^(\d+)\s*m(?:ins?|inutes?)?$', val)
    if m:
        return current_start - datetime.timedelta(minutes=int(m.group(1)))

    if re.match(r'^\d{1,2}:\d{2}(:\d{2})?\s*(am|pm)?$', val):
        start = parse_clock(val, current_start)
        if start > now:
            start -= datetime.timedelta(days=1)   # that time hasn't happened yet
        return start

    if re.match(r'^\d+$', val):
        return current_start - datetime.timedelta(minutes=int(val))

    raise ValueError("Try 45, 15m, 2h, 1.5h, or a time like 10:30.")


def parse_clock(text, reference):
    """Parse '3:05 PM', '15:05' or '15:05:30' onto reference's date."""
    t = (text or "").strip().lower().replace(".", "")
    m = re.match(r'^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(am|pm)?$', t)
    if not m:
        raise ValueError(f"Could not read the time {text!r}")
    hour, minute = int(m.group(1)), int(m.group(2))
    second = int(m.group(3) or 0)
    suffix = m.group(4)
    if suffix:
        if not 1 <= hour <= 12:
            raise ValueError(f"Hour out of range in {text!r}")
        hour = (hour % 12) + (12 if suffix == "pm" else 0)
    elif not 0 <= hour <= 23:
        raise ValueError(f"Hour out of range in {text!r}")
    if not 0 <= minute <= 59:
        raise ValueError(f"Minutes out of range in {text!r}")
    return reference.replace(hour=hour, minute=minute, second=second, microsecond=0)


# ── Dialog chrome ───────────────────────────────────────────────────
class Dialog(tk.Toplevel):
    def __init__(self, parent, title, width, height):
        super().__init__(parent, bg=T["bg"])
        self.result = None
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.geometry(f"{width}x{height}+{parent.winfo_rootx() + 30}"
                      f"+{max(parent.winfo_rooty() - 40, 40)}")
        self.body = tk.Frame(self, bg=T["bg"])
        self.body.pack(fill="both", expand=True, padx=PAD, pady=PAD)
        self.bind("<Escape>", lambda _e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def heading(self, text):
        tk.Label(self.body, text=text, bg=T["bg"], fg=T["text"],
                 font=(UI, 19, "bold"), anchor="w").pack(fill="x")

    def caption(self, text, pady=(18, 7)):
        tk.Label(self.body, text=text.upper(), bg=T["bg"], fg=T["muted"],
                 font=(UI, 10, "bold"), anchor="w").pack(fill="x", pady=pady)

    def textbox(self, parent=None, height=7):
        wrap = tk.Frame(parent or self.body, bg=T["bg"], highlightthickness=1,
                        highlightbackground=T["border2"])
        wrap.pack(fill="both", expand=True)
        box = tk.Text(wrap, height=height, wrap="word", bd=0, relief="flat",
                      bg=T["bg"], fg=T["text"], font=(UI, 13), highlightthickness=0,
                      padx=12, pady=10, insertbackground=T["text"])
        box.pack(fill="both", expand=True)
        return box

    def fit(self):
        """Resize to the content, bounded by the screen.

        A panel opening inside a fixed-height dialog pushes the buttons at the
        bottom out of reach — the window looks stuck because there is no longer
        any way to finish.
        """
        self.update_idletasks()
        h = min(self.winfo_reqheight(), self.winfo_screenheight() - 140)
        self.geometry(f"{self.winfo_width()}x{h}")

    def buttons(self, ok_text, cancel_text="Cancel", ok_tone="finish"):
        row = tk.Frame(self.body, bg=T["bg"])
        row.pack(fill="x", pady=(14, 0))
        # Equal columns: an unequal split made the pair read as two different
        # controls rather than two answers to the same question.
        row.columnconfigure(0, weight=1, uniform="btn")
        row.columnconfigure(1, weight=1, uniform="btn")
        Button(row, cancel_text, self._cancel, tone="neutral",
               height=BTN_H, size=BTN_SIZE, shadow=True).grid(
                   row=0, column=0, sticky="ew", padx=(0, 5))
        Button(row, ok_text, self._ok, tone=ok_tone,
               height=BTN_H, size=BTN_SIZE, shadow=True).grid(
                   row=0, column=1, sticky="ew", padx=(5, 0))

    def _ok(self):
        raise NotImplementedError

    def _cancel(self):
        self.result = None
        self.destroy()


class Notice(Dialog):
    def __init__(self, parent, title, message, tone="info"):
        super().__init__(parent, title, 360, 200)
        tk.Label(self.body, text=title, bg=T["bg"],
                 fg=T["danger"] if tone == "error" else T["text"],
                 font=(UI, 16, "bold"), anchor="w").pack(fill="x")
        tk.Label(self.body, text=message, bg=T["bg"], fg=T["muted"], font=(UI, 12),
                 anchor="w", justify="left", wraplength=300).pack(fill="x", pady=(8, 0))
        row = tk.Frame(self.body, bg=T["bg"])
        row.pack(fill="x", side="bottom")
        Button(row, "OK", self._cancel, tone="finish", height=BTN_H,
               size=BTN_SIZE, shadow=True).pack(fill="x")
        self.grab_set()
        self.wait_window(self)


class ConfirmDialog(Dialog):
    """Yes/no for something that cannot be undone."""

    def __init__(self, parent, title, message, confirm="Delete"):
        super().__init__(parent, title, 380, 220)
        tk.Label(self.body, text=title, bg=T["bg"], fg=T["text"],
                 font=(UI, 16, "bold"), anchor="w").pack(fill="x")
        tk.Label(self.body, text=message, bg=T["bg"], fg=T["muted"], font=(UI, 12),
                 anchor="w", justify="left", wraplength=320).pack(fill="x", pady=(8, 0))
        row = tk.Frame(self.body, bg=T["bg"])
        row.pack(fill="x", side="bottom")
        row.columnconfigure(0, weight=1, uniform="btn")
        row.columnconfigure(1, weight=1, uniform="btn")
        Button(row, "Keep it", self._cancel, tone="neutral", height=BTN_H,
               size=BTN_SIZE, shadow=True).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        Button(row, confirm, self._ok, tone="danger", height=BTN_H,
               size=BTN_SIZE, shadow=True).grid(row=0, column=1, sticky="ew", padx=(5, 0))
        self.fit()
        self.grab_set()
        self.wait_window(self)

    def _ok(self):
        self.result = True
        self.destroy()


class ChoiceDialog(Dialog):
    """A warning with several ways out, stacked one per row.

    Used where something is unfinished and there is no single safe default —
    quitting with a timer still running, or abandoning typed notes.
    """

    def __init__(self, parent, title, message, choices, height=270):
        super().__init__(parent, title, 400, height)
        tk.Label(self.body, text=title, bg=T["bg"], fg=T["text"],
                 font=(UI, 16, "bold"), anchor="w").pack(fill="x")
        tk.Label(self.body, text=message, bg=T["bg"], fg=T["muted"], font=(UI, 12),
                 anchor="w", justify="left", wraplength=340).pack(fill="x", pady=(8, 14))
        for label, value, kind in choices:
            tone = {"danger": "danger", "primary": "finish",
                    "secondary": "neutral"}.get(kind, "neutral")
            Button(self.body, label, lambda v=value: self._pick(v), tone=tone,
                   height=BTN_H, size=BTN_SIZE, shadow=True).pack(fill="x", pady=(0, 8))
        self.fit()
        self.grab_set()
        self.wait_window(self)

    def _pick(self, value):
        self.result = value
        self.destroy()


class AdjustStartDialog(Dialog):
    """Pull a running timer's start time backwards.

    Mirrors the menu bar app's Custom Adjustment, for when you start the timer
    a few minutes after actually starting work.
    """

    def __init__(self, parent, project, start_dt):
        super().__init__(parent, "Adjust Start", 380, 400)
        self.start_dt = start_dt
        self.new_start = start_dt

        self.heading("Adjust start time")
        tk.Label(self.body, text=project, bg=T["bg"], fg=T["muted"],
                 font=(UI, 13), anchor="w").pack(fill="x", pady=(4, 0))

        self.caption("Quick")
        quick = tk.Frame(self.body, bg=T["bg"])
        quick.pack(fill="x")
        for i, mins in enumerate((5, 15, 30)):
            quick.columnconfigure(i, weight=1)
            Button(quick, f"−{mins} min", lambda m=mins: self._shift(m),
                   height=BTN_H, size=BTN_SIZE, shadow=True).grid(row=0, column=i, sticky="ew",
                                            padx=(0 if i == 0 else 5, 0))

        self.caption("Or type an amount")
        wrap = tk.Frame(self.body, bg=T["bg"], highlightthickness=1,
                        highlightbackground=T["border2"], height=FIELD_H)
        wrap.pack(fill="x")
        wrap.pack_propagate(False)
        self.entry = tk.Entry(wrap, bd=0, relief="flat", bg=T["bg"], fg=T["text"],
                              highlightthickness=0, font=(UI, 15),
                              insertbackground=T["text"])
        self.entry.pack(fill="both", expand=True, padx=13)
        self.entry.bind("<KeyRelease>", lambda _e: self._from_text())
        tk.Label(self.body, text="45 · 15m · 2h · 1.5h · or a time like 10:30",
                 bg=T["bg"], fg=T["muted"], font=(UI, 11), anchor="w").pack(
                     fill="x", pady=(6, 0))

        self.lbl_preview = tk.Label(self.body, bg=T["bg"], fg=T["text"],
                                    font=(UI, 14, "bold"), anchor="w")
        self.lbl_preview.pack(fill="x", pady=(14, 0))
        self.lbl_err = tk.Label(self.body, bg=T["bg"], fg=T["danger"],
                                font=(UI, 11), anchor="w")
        self.lbl_err.pack(fill="x", pady=(4, 0))

        self.buttons("Save")
        self._preview()
        self.fit()
        self.entry.focus_set()
        self.grab_set()
        self.wait_window(self)

    def _shift(self, minutes):
        self.new_start = self.new_start - datetime.timedelta(minutes=minutes)
        self.lbl_err.config(text="")
        self.entry.delete(0, "end")
        self._preview()

    def _from_text(self):
        raw = self.entry.get().strip()
        if not raw:
            self.new_start = self.start_dt
            self.lbl_err.config(text="")
            self._preview()
            return
        try:
            self.new_start = parse_adjustment(raw, self.start_dt)
        except ValueError as e:
            self.lbl_err.config(text=str(e))
            return
        self.lbl_err.config(text="")
        self._preview()

    def _preview(self):
        elapsed = datetime.datetime.now() - self.new_start
        self.lbl_preview.config(
            text=f"Starts {self.new_start:%-I:%M %p}  ·  {fmt_elapsed(elapsed)} elapsed")

    def _ok(self):
        now = datetime.datetime.now()
        if self.new_start > now:
            self.lbl_err.config(text="That start time is in the future.")
            return
        if (now - self.new_start).total_seconds() / 3600.0 > MAX_SESSION_HOURS:
            self.lbl_err.config(
                text=f"That would make the session over {MAX_SESSION_HOURS} h.")
            return
        self.result = self.new_start.isoformat()
        self.destroy()


class StopDialog(Dialog):
    """Stop the timer: confirm/correct the time, then write the notes.

    Shows the raw session length and, separately, the day's bucket for this
    project with the invoice's 0.1 h round-up applied — because that bucket,
    not the session, is what actually gets billed.
    """

    def __init__(self, parent, project, start_dt, end_dt, projects=()):
        super().__init__(parent, "Stop Timer", 430, 660)
        # Vertically resizable as a backstop: fit() sizes to the content, but
        # on a short screen the user must still be able to reach Save.
        self.resizable(False, True)
        self.project = project
        self.start_dt = start_dt
        self.end_dt = end_dt
        self.adjust_open = False
        # Offer the presets plus whatever this entry is already on, in case it
        # was started as a one-off custom name.
        self.projects = list(projects) or [project]
        if project not in self.projects:
            self.projects.insert(0, project)

        self.heading("Stop timer")
        self.caption("Time logged", pady=(16, 7))

        card = tk.Frame(self.body, bg=T["surface"], highlightthickness=1,
                        highlightbackground=T["border"])
        card.pack(fill="x")
        inner = tk.Frame(card, bg=T["surface"])
        inner.pack(fill="x", padx=16, pady=14)

        self.lbl_project = tk.Label(inner, text=project, bg=T["surface"],
                                    fg=T["text"], font=(UI, 16, "bold"), anchor="w")
        self.lbl_project.pack(fill="x")

        row = tk.Frame(inner, bg=T["surface"])
        row.pack(fill="x", pady=(8, 0))
        self.lbl_clock = tk.Label(row, bg=T["surface"], fg=T["text"],
                                  font=(MONO, 30, "bold"))
        self.lbl_clock.pack(side="left")
        self.lbl_dec = tk.Label(row, bg=T["surface"], fg=T["muted"], font=(UI, 14))
        self.lbl_dec.pack(side="left", padx=(10, 0), pady=(8, 0))

        self.lbl_range = tk.Label(inner, bg=T["surface"], fg=T["muted"],
                                  font=(UI, 13), anchor="w")
        self.lbl_range.pack(fill="x", pady=(8, 0))

        tk.Frame(inner, bg=T["border"], height=1).pack(fill="x", pady=10)

        self.lbl_bucket = tk.Label(inner, bg=T["surface"], fg=T["text"],
                                   font=(UI, 13), anchor="w", justify="left")
        self.lbl_bucket.pack(fill="x")
        self.lbl_note = tk.Label(inner, bg=T["surface"], fg=T["muted"],
                                 font=(UI, 11), anchor="w", justify="left",
                                 wraplength=350)
        self.lbl_note.pack(fill="x", pady=(4, 0))

        self.btn_adjust = Button(inner, "Adjust", self._toggle_adjust,
                                 height=BTN_H, size=BTN_SIZE, shadow=True)
        self.btn_adjust.pack(fill="x", pady=(12, 0))

        # Adjust fields, hidden until asked for
        self.adjust = tk.Frame(inner, bg=T["surface"])
        self.adjust.columnconfigure(0, weight=1)
        self.adjust.columnconfigure(1, weight=1)

        proj_cell = tk.Frame(self.adjust, bg=T["surface"])
        proj_cell.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        tk.Label(proj_cell, text="PROJECT", bg=T["surface"], fg=T["muted"],
                 font=(UI, 9, "bold"), anchor="w").pack(fill="x")
        self.in_project = ProjectPicker(proj_cell, self.projects)
        self.in_project.pack(fill="x", pady=(4, 0))
        self.in_project.var.set(project)
        self.in_project.var.trace_add("write", lambda *_a: self._on_project_change())

        self.in_start = self._field(self.adjust, "START", 1, 0)
        self.in_end = self._field(self.adjust, "END", 1, 1)
        self.in_dur = self._field(self.adjust, "OR DURATION IN HOURS", 2, 0, span=2)
        for e in (self.in_start, self.in_end):
            e.bind("<KeyRelease>", lambda _e: self._from_clocks())
        self.in_dur.bind("<KeyRelease>", lambda _e: self._from_duration())
        self.lbl_err = tk.Label(self.adjust, bg=T["surface"], fg=T["danger"],
                                font=(UI, 11), anchor="w")
        self.lbl_err.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        self.caption("Notes")
        self.box = self.textbox(height=6)
        self.box.bind("<KeyRelease>", lambda _e: self._refresh())

        hint = tk.Frame(self.body, bg=T["bg"])
        hint.pack(fill="x", pady=(7, 0))
        tk.Label(hint, text="Goes onto the invoice line for this day",
                 bg=T["bg"], fg=T["muted"], font=(UI, 11)).pack(side="left")

        self.buttons("Save entry")
        self._sync_fields()
        self._refresh()
        self.fit()
        self.box.focus_set()
        self.grab_set()
        self.wait_window(self)

    def _field(self, parent, label, row, col, span=1):
        cell = tk.Frame(parent, bg=T["surface"])
        cell.grid(row=row, column=col, columnspan=span, sticky="ew",
                  padx=(0, 5) if (col == 0 and span == 1) else (5, 0) if col else 0,
                  pady=(8, 0))
        tk.Label(cell, text=label, bg=T["surface"], fg=T["muted"],
                 font=(UI, 9, "bold"), anchor="w").pack(fill="x")
        wrap = tk.Frame(cell, bg=T["bg"], highlightthickness=1,
                        highlightbackground=T["border2"], height=FIELD_H)
        wrap.pack(fill="x", pady=(4, 0))
        wrap.pack_propagate(False)
        entry = tk.Entry(wrap, bd=0, relief="flat", bg=T["bg"], fg=T["text"],
                         highlightthickness=0, font=(UI, 14, "bold"),
                         insertbackground=T["text"])
        entry.pack(fill="both", expand=True, padx=11)
        return entry

    def _on_project_change(self):
        name = self.in_project.get()
        if not name:
            return
        self.project = name
        self.lbl_project.config(text=name)
        self._refresh()   # a different project means a different day bucket

    def _toggle_adjust(self):
        self.adjust_open = not self.adjust_open
        # Re-pack the toggle so it sits *below* the fields while they are open:
        # a "Back" control above the panel it leaves reads backwards.
        self.btn_adjust.pack_forget()
        if self.adjust_open:
            self.adjust.pack(fill="x")
            self.btn_adjust.set_text("←  Back")
            self.btn_adjust.pack(fill="x", pady=(12, 0))
        else:
            self.adjust.pack_forget()
            self.btn_adjust.set_text("Adjust")
            self.btn_adjust.pack(fill="x", pady=(12, 0))
        self.fit()

    def _sync_fields(self):
        for entry, value in ((self.in_start, self.start_dt.strftime('%-I:%M %p')),
                             (self.in_end, self.end_dt.strftime('%-I:%M %p')),
                             (self.in_dur, f"{self._hours():.2f}")):
            entry.delete(0, "end")
            entry.insert(0, value)

    def _hours(self):
        return max((self.end_dt - self.start_dt).total_seconds() / 3600.0, 0.0)

    def _from_clocks(self):
        try:
            start = parse_clock(self.in_start.get(), self.start_dt)
            # Anchor the end to the START's date, never to the current end_dt:
            # anchoring to end_dt makes a past-midnight roll permanent, so a
            # later correction back to an earlier time stays a day out.
            end = parse_clock(self.in_end.get(), start)
        except ValueError as e:
            self.lbl_err.config(text=str(e))
            return
        if end <= start:
            end += datetime.timedelta(days=1)  # session ran past midnight
        self.start_dt, self.end_dt = start, end
        self.lbl_err.config(text="")
        self.in_dur.delete(0, "end")
        self.in_dur.insert(0, f"{self._hours():.2f}")
        self._refresh()

    def _from_duration(self):
        raw = self.in_dur.get().strip()
        try:
            hours = float(raw)
        except ValueError:
            self.lbl_err.config(text="Enter the duration as a number, e.g. 2.25")
            return
        if hours <= 0:
            self.lbl_err.config(text="Duration must be greater than 0.")
            return
        if hours > MAX_SESSION_HOURS:
            self.lbl_err.config(
                text=f"That's over {MAX_SESSION_HOURS} h — check the figure.")
            return
        self.end_dt = self.start_dt + datetime.timedelta(hours=hours)
        self.lbl_err.config(text="")
        self.in_end.delete(0, "end")
        self.in_end.insert(0, self.end_dt.strftime('%-I:%M %p'))
        self._refresh()

    def _refresh(self):
        session_h = self._hours()
        self.lbl_clock.config(text=fmt_elapsed(self.end_dt - self.start_dt))
        self.lbl_dec.config(text=f"{session_h:.2f} h")
        same_day = self.start_dt.date() == self.end_dt.date()
        self.lbl_range.config(
            text=f"{self.start_dt.strftime('%-I:%M %p')}  →  "
                 f"{self.end_dt.strftime('%-I:%M %p')}"
                 f"{'' if same_day else '  (next day)'}")

        # The invoice derives the item code from the notes, so it is not shown
        # or warned about here — it changes as you type, and flagging it read
        # as a restriction rather than a description of what the invoice does.
        code = classify(self.box.get("1.0", "end").strip())

        if self.project in EXCLUDE_PROJECTS:
            self.lbl_bucket.config(text="Not billed", fg=T["muted"])
            self.lbl_note.config(text=f"'{self.project}' is in EXCLUDE_PROJECTS, "
                                      f"so it never reaches an invoice.")
            return

        day = self.start_dt.date()
        prior_same_code, codes_today = day_bucket(self.project, day, item_code=code)
        # Only the part of this session the invoice bills on `day` — an
        # overnight session is split across two days, not heaped on the first.
        shares = day_shares(self.start_dt, self.end_dt)
        this_day = session_share(self.start_dt, self.end_dt, day)
        bucket_raw = prior_same_code + this_day
        self.lbl_bucket.config(
            text=f"{self.project} {day:%b %-d}:  {bucket_raw:.2f} h  →  "
                 f"{billable(bucket_raw):.1f} h billable", fg=T["text"])

        bits = []
        if prior_same_code > 0:
            bits.append(f"Includes {prior_same_code:.2f} h already logged that day. "
                        f"The 0.1 h round-up applies to the day's total, not to "
                        f"each session.")
        spill = [(d, h) for d, h in shares if d != day]
        if spill:
            parts = ", ".join(f"{h:.2f} h on {d:%b %-d}" for d, h in spill)
            bits.append(f"This session runs past midnight, so the invoice bills "
                        f"{parts} as a separate line.")
        self.lbl_note.config(text=" ".join(bits), fg=T["muted"])

    def _cancel(self):
        """Don't silently throw away typed notes."""
        if self.box.get("1.0", "end").strip():
            choice = ChoiceDialog(
                self, "Discard these notes?",
                "You've written notes that haven't been saved. The timer stays "
                "as it is either way — only the notes are lost.",
                [("Keep editing", "keep", "secondary"),
                 ("Discard the notes", "discard", "danger")],
                height=250)
            if choice.result != "discard":
                return
        self.result = None
        self.destroy()

    def _ok(self):
        if self._hours() <= 0:
            self.lbl_err.config(text="The end time must be after the start time.")
            return
        if not self.project.strip():
            self.lbl_err.config(text="Pick or type a project name.")
            return
        self.result = (self.box.get("1.0", "end").strip(),
                       self.start_dt.isoformat(), self.end_dt.isoformat(),
                       self.project.strip())
        self.destroy()


class LogHoursDialog(Dialog):
    def __init__(self, parent, projects):
        super().__init__(parent, "Log Hours", 430, 460)
        self.heading("Log hours manually")
        self.caption("Project", pady=(16, 7))
        self.picker = ProjectPicker(self.body, projects)
        self.picker.pack(fill="x")

        self.caption("Hours")
        wrap = tk.Frame(self.body, bg=T["bg"], highlightthickness=1,
                        highlightbackground=T["border2"], height=FIELD_H)
        wrap.pack(fill="x")
        wrap.pack_propagate(False)
        self.hours = tk.Entry(wrap, bd=0, relief="flat", bg=T["bg"], fg=T["text"],
                              highlightthickness=0, font=(UI, 15, "bold"),
                              insertbackground=T["text"])
        self.hours.pack(fill="both", expand=True, padx=13)

        self.caption("Description (optional)")
        self.desc = self.textbox(height=4)
        self.lbl_err = tk.Label(self.body, bg=T["bg"], fg=T["danger"],
                                font=(UI, 11), anchor="w")
        self.lbl_err.pack(fill="x", pady=(7, 0))
        self.buttons("Log hours")
        self.hours.focus_set()
        self.grab_set()
        self.wait_window(self)

    def _ok(self):
        project = self.picker.get()
        if not project:
            self.lbl_err.config(text="Pick or type a project name.")
            return
        try:
            hours = float(self.hours.get().strip())
        except ValueError:
            self.lbl_err.config(text="Enter hours as a number, e.g. 5.5")
            return
        if hours <= 0:
            self.lbl_err.config(text="Hours must be greater than 0.")
            return
        if hours > MAX_SESSION_HOURS:
            self.lbl_err.config(
                text=f"That's over {MAX_SESSION_HOURS} h — check the figure, "
                     f"or split it across days.")
            return
        self.result = (project, hours, self.desc.get("1.0", "end").strip())
        self.destroy()


# ── Layout views ────────────────────────────────────────────────────
class ExpandedView(tk.Frame):
    """The tall layout: status, project, big clock, actions, totals."""

    def __init__(self, parent, app):
        super().__init__(parent, bg=T["bg"])
        self.app = app
        wrap = tk.Frame(self, bg=T["bg"])
        wrap.pack(fill="both", expand=True, padx=PAD, pady=(22, 16))

        pill = tk.Frame(wrap, bg=T["bg"], height=20)
        pill.pack(fill="x")
        self.dot = tk.Label(pill, text="●", bg=T["bg"], fg=T["idle"], font=(UI, 12))
        self.dot.pack(side="left")
        self.state = tk.Label(pill, text="IDLE", bg=T["bg"], fg=T["muted"],
                              font=(UI, 14, "bold"))
        self.state.pack(side="left", padx=(6, 0))

        tk.Label(wrap, text="PROJECT", bg=T["bg"], fg=T["muted"],
                 font=(UI, 11, "bold"), anchor="w").pack(fill="x", pady=(16, 0))

        zone = tk.Frame(wrap, bg=T["bg"], height=FIELD_H)
        zone.pack(fill="x", pady=(7, 0))
        zone.pack_propagate(False)
        self.project = tk.Label(zone, text="—", bg=T["bg"], fg=T["text"],
                                font=(UI, 19, "bold"), anchor="w")
        self.picker = ProjectPicker(zone, app.projects)

        self.clock = tk.Label(wrap, text="0:00:00", bg=T["bg"], fg=T["ghost"],
                              font=(MONO, 46, "bold"), anchor="w")
        self.clock.pack(fill="x", pady=(12, 0))
        self.meta = tk.Label(wrap, text="", bg=T["bg"], fg=T["muted"],
                             font=(UI, 14), anchor="w")
        self.meta.pack(fill="x", pady=(5, 0))

        self.actions = tk.Frame(wrap, bg=T["bg"])
        self.actions.pack(fill="x", pady=(20, 0))
        self.actions.columnconfigure(0, weight=1)
        self.actions.columnconfigure(1, weight=1)
        self.btn_start = Button(self.actions, "Start Timer", app.on_start,
                                tone="go", height=BTN_H, size=BTN_SIZE, shadow=True)
        self.btn_pause = Button(self.actions, "Pause", app.on_pause_resume,
                                tone="hold", height=BTN_H, size=BTN_SIZE, shadow=True)
        self.btn_stop = Button(self.actions, "Stop", app.on_stop,
                               tone="finish", height=BTN_H, size=BTN_SIZE, shadow=True)

        # Only meaningful while a timer exists, so packed/unpacked with state.
        self.extra = tk.Frame(wrap, bg=T["bg"])
        self.extra.columnconfigure(0, weight=1)
        self.extra.columnconfigure(1, weight=1)
        Button(self.extra, "Adjust start", app.on_adjust_start,
               height=BTN_H, size=BTN_SIZE, shadow=True).grid(row=0, column=0, sticky="ew",
                                                     padx=(0, 5))
        Button(self.extra, "Discard", app.on_discard, tone="danger",
               height=BTN_H, size=BTN_SIZE, shadow=True).grid(row=0, column=1,
                                                     sticky="ew", padx=(5, 0))

        self.btn_log = Button(wrap, "+  Log hours manually", app.on_log_hours,
                              kind="ghost", height=BTN_H, size=BTN_SIZE)
        self.btn_log.pack(fill="x", pady=(9, 0))

        # Everything flows top-down with fixed gaps. Pinning the footer to the
        # bottom instead made every extra pixel of window height pool in one
        # gap in the middle, so the spacing never looked the same at two sizes.
        tk.Frame(wrap, bg=T["border"], height=1).pack(fill="x", pady=(16, 0))

        stats = tk.Frame(wrap, bg=T["bg"])
        stats.pack(fill="x", pady=(13, 0))
        stats.columnconfigure(0, weight=1)
        stats.columnconfigure(1, weight=1)
        self.today = self._stat(stats, 0, "TODAY")
        self.week = self._stat(stats, 1, "THIS WEEK")

        footer = tk.Frame(wrap, bg=T["bg"])
        footer.pack(fill="x", pady=(14, 0))
        tk.Label(footer, text="Always on top", bg=T["bg"], fg=T["muted"],
                 font=(UI, 13)).pack(side="left")
        self.toggle = Toggle(footer, value=app.settings.get("always_on_top", False),
                             command=app.on_toggle_top)
        self.toggle.pack(side="right")

        self._mode = None

    def _stat(self, parent, col, caption):
        cell = tk.Frame(parent, bg=T["bg"])
        cell.grid(row=0, column=col, sticky="ew")
        value = tk.Label(cell, text="—", bg=T["bg"], fg=T["text"], font=(UI, 19, "bold"))
        value.pack()
        tk.Label(cell, text=caption, bg=T["bg"], fg=T["muted"],
                 font=(UI, 10, "bold")).pack(pady=(2, 0))
        return value

    def apply(self, s):
        self.dot.config(fg=s["colour"])
        self.state.config(text=s["state"], fg=s["label_colour"])
        self.clock.config(text=s["clock"], fg=s["clock_colour"])
        self.meta.config(text=s["meta"])
        self.today.config(text=f"{s['today']:.1f}h")
        self.week.config(text=f"{s['week']:.1f}h")

        mode_changed = s["mode"] != self._mode
        if mode_changed:
            self._mode = s["mode"]
            self.project.pack_forget()
            self.picker.pack_forget()
            for b in (self.btn_start, self.btn_pause, self.btn_stop):
                b.grid_forget()
            self.extra.pack_forget()
            if s["mode"] == "idle":
                self.picker.pack(fill="both", expand=True)
                self.btn_start.grid(row=0, column=0, columnspan=2, sticky="ew")
            else:
                self.project.pack(fill="both", expand=True)
                self.btn_pause.grid(row=0, column=0, sticky="ew", padx=(0, 5))
                self.btn_stop.grid(row=0, column=1, sticky="ew", padx=(5, 0))
                self.extra.pack(fill="x", pady=(8, 0), after=self.actions)
        if s["mode"] != "idle":
            self.project.config(text=s["project"])
        paused = s["mode"] == "paused"
        self.btn_pause.set_text("Resume" if paused else "Pause")
        # Resume is a "go" action, Pause is a "hold" one — same button, so it
        # takes the colour of whichever it currently is.
        self.btn_pause.set_tone("go" if paused else "hold")
        if mode_changed:
            # Running adds two buttons, so the content is taller than when idle;
            # re-pin so the window tracks it in both directions.
            self.app.fit_height()


class CompactView(tk.Frame):
    """The short layout: one line with clock, project and the controls."""

    def __init__(self, parent, app):
        super().__init__(parent, bg=T["bg"])
        self.app = app
        wrap = tk.Frame(self, bg=T["bg"])
        wrap.pack(fill="both", expand=True, padx=18, pady=16)

        top = tk.Frame(wrap, bg=T["bg"])
        top.pack(fill="x")
        self.dot = tk.Label(top, text="●", bg=T["bg"], fg=T["idle"], font=(UI, 12))
        self.dot.pack(side="left")
        self.state = tk.Label(top, text="IDLE", bg=T["bg"], fg=T["muted"],
                              font=(UI, 14, "bold"))
        self.state.pack(side="left", padx=(6, 0))

        self.week = self._stat(top, "THIS WEEK")
        self.today = self._stat(top, "TODAY")

        row = tk.Frame(wrap, bg=T["bg"])
        row.pack(fill="x", pady=(10, 0))

        self.btn_stop = Button(row, "Stop", app.on_stop, tone="finish", height=BTN_H, size=BTN_SIZE, shadow=True)
        self.btn_stop.pack(side="right", padx=(8, 0))
        self.btn_stop.config(width=74)
        self.btn_pause = Button(row, "Pause", app.on_pause_resume, tone="hold", height=BTN_H, size=BTN_SIZE, shadow=True)
        self.btn_pause.pack(side="right", padx=(8, 0))
        self.btn_pause.config(width=74)
        self.btn_start = Button(row, "Start", app.on_start, tone="go", height=BTN_H, size=BTN_SIZE, shadow=True)
        self.btn_start.config(width=74)

        left = tk.Frame(row, bg=T["bg"])
        left.pack(side="left", fill="both", expand=True)
        self.clock = tk.Label(left, text="0:00:00", bg=T["bg"], fg=T["ghost"],
                              font=(MONO, 32, "bold"), anchor="w")
        self.clock.pack(fill="x")
        self.meta = tk.Label(left, text="", bg=T["bg"], fg=T["muted"],
                             font=(UI, 13), anchor="w")
        self.meta.pack(fill="x", pady=(3, 0))
        self._mode = None

    def _stat(self, parent, caption):
        cell = tk.Frame(parent, bg=T["bg"])
        cell.pack(side="right", padx=(16, 0))
        value = tk.Label(cell, text="—", bg=T["bg"], fg=T["text"], font=(UI, 16, "bold"))
        value.pack(anchor="e")
        tk.Label(cell, text=caption, bg=T["bg"], fg=T["muted"],
                 font=(UI, 9, "bold")).pack(anchor="e")
        return value

    def apply(self, s):
        self.dot.config(fg=s["colour"])
        self.state.config(text=s["state"], fg=s["label_colour"])
        self.clock.config(text=s["clock"], fg=s["clock_colour"])
        self.today.config(text=f"{s['today']:.1f}h")
        self.week.config(text=f"{s['week']:.1f}h")
        meta = s["project"] if s["mode"] != "idle" else "No timer"
        self.meta.config(text=f"{meta}  ·  {s['meta']}")
        if s["mode"] != self._mode:
            self._mode = s["mode"]
            for b in (self.btn_start, self.btn_pause, self.btn_stop):
                b.pack_forget()
            if s["mode"] == "idle":
                self.btn_start.pack(side="right", padx=(8, 0))
            else:
                self.btn_stop.pack(side="right", padx=(8, 0))
                self.btn_pause.pack(side="right", padx=(8, 0))
        paused = s["mode"] == "paused"
        self.btn_pause.set_text("Resume" if paused else "Pause")
        self.btn_pause.set_tone("go" if paused else "hold")


# ── Main window ─────────────────────────────────────────────────────
class TimerApp:
    def __init__(self, root):
        self.root = root
        self.settings = load_settings()
        self.projects = load_projects()
        self._layout = None
        self._resize_job = None
        self._poll_job = None
        self._ready = False

        root.title("Time Tracker")
        root.configure(bg=T["bg"])
        root.geometry(sane_geometry(self.settings.get("geometry")))
        root.minsize(MIN_W, 118)

        self.expanded = ExpandedView(root, self)
        self.compact = CompactView(root, self)
        for view in (self.expanded, self.compact):
            bind_double_click(view, self.toggle_size)
        self.apply_topmost()

        root.bind("<Configure>", self._on_configure)
        root.bind("<Map>", self._on_map, add="+")
        self._set_layout("expanded" if self._height() >= BREAKPOINT_H else "compact")
        self.refresh()

    def _on_map(self, _event):
        """Start honouring resize events only once the window has settled.

        While mapping, Tk reports transient heights well under the real one.
        Acting on those opens the window in the compact layout for a moment
        before it snaps to the right one — a visible flash on every launch.
        """
        if not self._ready:
            self.root.after(SETTLE_MS, self._mark_ready)

    def _mark_ready(self):
        self._ready = True
        want = "expanded" if self.root.winfo_height() >= BREAKPOINT_H else "compact"
        self._set_layout(want)
        self.fit_height(exact=True)

    def fit_height(self, exact=True):
        """Pin the window to the height of its content.

        The expanded view is capped with maxsize rather than merely resized, so
        the window cannot be dragged taller than it needs — trailing white space
        under the footer serves no purpose and just looks like a mistake. The
        cap always tracks the *expanded* height so a collapsed window can still
        be dragged back up; dragging shorter still collapses to the bar.
        """
        self.root.update_idletasks()
        need = min(self.expanded.winfo_reqheight(),
                   self.root.winfo_screenheight() - 140)
        # Cap the width too. Leaving it at the screen width let the green zoom
        # button stretch the window right across the display — and the result
        # was then saved and restored on the next launch.
        self.root.maxsize(MAX_W, need)
        if self._layout == "expanded" and (exact or self.root.winfo_height() < need):
            self.root.geometry(f"{self.root.winfo_width()}x{need}")

    def toggle_size(self):
        """Snap between the two sizes — bound to a double-click on the window."""
        if self._layout == "expanded":
            self.settings["geometry"] = self.root.winfo_geometry()
            save_settings(self.settings)
            self.root.geometry(f"{max(self.root.winfo_width(), MIN_W)}x{COMPACT_HEIGHT}")
            self._set_layout("compact")
        else:
            spec = self.settings.get("geometry", DEFAULT_GEOMETRY)
            try:
                tall = int(re.split(r'[+-]', spec.split("x")[1])[0])
            except (ValueError, IndexError):
                tall = DEFAULT_HEIGHT
            if tall < EXPAND_ABOVE:          # last saved size was itself compact
                tall = DEFAULT_HEIGHT
            self.root.geometry(f"{max(self.root.winfo_width(), MIN_W)}x{tall}")
            self._set_layout("expanded")
            self.fit_height(exact=True)

    def _height(self):
        """Window height, or the height we are about to be given.

        An unmapped Tk window reports a placeholder height (200 on macOS), not
        0 or 1 — so ask whether it is mapped rather than testing the number,
        and fall back to the geometry string we just set.
        """
        if self.root.winfo_ismapped():
            return self.root.winfo_height()
        spec = self.settings.get("geometry", DEFAULT_GEOMETRY)
        try:
            return int(re.split(r'[+-]', spec.split("x")[1])[0])
        except (ValueError, IndexError):
            return DEFAULT_HEIGHT

    def _on_configure(self, event):
        if event.widget is not self.root or not self._ready:
            return
        h = self.root.winfo_height()
        if h < COLLAPSE_BELOW:
            want = "compact"
        elif h > EXPAND_ABOVE:
            want = "expanded"
        else:
            return  # inside the dead zone: keep whichever layout is showing
        if want != self._layout:
            self._set_layout(want)

    def _set_layout(self, want):
        self._resize_job = None
        if want == self._layout:
            return
        self._layout = want
        self.expanded.pack_forget()
        self.compact.pack_forget()
        (self.expanded if want == "expanded" else self.compact).pack(fill="both", expand=True)
        self.refresh(reschedule=False)
        if self._ready:
            self.fit_height()

    @property
    def view(self):
        return self.expanded if self._layout == "expanded" else self.compact

    # ── State ───────────────────────────────────────────────────────
    def apply_topmost(self):
        self.root.attributes('-topmost', bool(self.settings.get("always_on_top", False)))

    def on_toggle_top(self, value):
        self.settings["always_on_top"] = value
        save_settings(self.settings)
        self.apply_topmost()

    def refresh(self, reschedule=True):
        try:
            active = db_logic.get_active_timer()
            paused = None if active else paused_row()
            today_h, week_h = period_totals()
            s = {"today": today_h, "week": week_h}

            if active:
                start = datetime.datetime.fromisoformat(active["start_time"])
                s.update(mode="running", state="RUNNING", colour=T["running"],
                         label_colour=T["runlabel"], project=active["project_name"],
                         clock=fmt_elapsed(datetime.datetime.now() - start),
                         clock_colour=T["text"],
                         meta=f"Started {start.strftime('%-I:%M %p')}")
            elif paused:
                start = datetime.datetime.fromisoformat(paused["start_time"])
                end = datetime.datetime.fromisoformat(paused["end_time"])
                s.update(mode="paused", state="PAUSED", colour=T["paused"],
                         label_colour=T["pauselbl"], project=paused["project_name"],
                         clock=fmt_elapsed(end - start), clock_colour=T["muted"],
                         meta=f"Paused at {end.strftime('%-I:%M %p')}")
            else:
                last = db_logic.get_last_ended_timer()
                meta = "Nothing running"
                if last and last.get("end_time"):
                    try:
                        ended = datetime.datetime.fromisoformat(last["end_time"])
                        meta = (f"Last: {last['project_name']} · "
                                f"ended {ended.strftime('%-I:%M %p')}")
                    except (TypeError, ValueError):
                        pass
                s.update(mode="idle", state="IDLE", colour=T["idle"],
                         label_colour=T["muted"], project="—", clock="0:00:00",
                         clock_colour=T["ghost"], meta=meta)

            self.view.apply(s)
        except Exception as e:
            self.view.meta.config(text=f"Error: {e}")

        if reschedule:
            self._poll_job = self.root.after(POLL_MS, self.refresh)

    # ── Actions ─────────────────────────────────────────────────────
    def _guard(self, fn, failure_title):
        try:
            fn()
            return True
        except Exception as e:
            Notice(self.root, failure_title, f"{type(e).__name__}: {e}", tone="error")
            return False

    def on_start(self):
        # The picker lives on the expanded view but holds its value whether or
        # not that view is packed, so compact-mode Start uses the same choice
        # rather than silently defaulting to the first project.
        project = self.expanded.picker.get()
        if not project:
            Notice(self.root, "Missing project", "Pick or type a project name first.")
            return
        self._guard(lambda: db_logic.start_timer(project), "Could not start timer")
        self.refresh(reschedule=False)

    def on_pause_resume(self):
        if db_logic.get_active_timer():
            self._guard(lambda: db_logic.stop_timer("[Paused]"), "Could not pause")
        elif paused_row():
            self._guard(db_logic.resume_paused_timer, "Could not resume")
        self.refresh(reschedule=False)

    def on_stop(self):
        active = db_logic.get_active_timer()
        paused = None if active else paused_row()
        if not active and not paused:
            Notice(self.root, "Nothing running", "There's no active timer to stop.")
            return

        if active:
            project = active["project_name"]
            start = datetime.datetime.fromisoformat(active["start_time"])
            end = datetime.datetime.now().replace(microsecond=0)
        else:
            project = paused["project_name"]
            start = datetime.datetime.fromisoformat(paused["start_time"])
            end = datetime.datetime.fromisoformat(paused["end_time"])

        dlg = StopDialog(self.root, project, start, end, self.projects)
        if dlg.result is None:
            return  # cancelled — leave the timer alone
        desc, start_iso, end_iso, proj = dlg.result

        if active:
            self._guard(
                lambda: db_logic.stop_timer_with(desc, start_iso, end_iso, proj),
                "Could not stop timer")
        else:
            # Already closed in the DB with a '[Paused]' placeholder; overwrite it.
            self._guard(
                lambda: db_logic.update_last_entry(desc, start_iso, end_iso, proj),
                "Could not save entry")
        self.refresh(reschedule=False)

    def on_adjust_start(self):
        active = db_logic.get_active_timer()
        paused = None if active else paused_row()
        row = active or paused
        if not row:
            Notice(self.root, "Nothing running", "There's no timer to adjust.")
            return
        if paused:
            Notice(self.root, "Timer is paused",
                   "Resume the timer first, then adjust its start time.")
            return
        start = datetime.datetime.fromisoformat(row["start_time"])
        dlg = AdjustStartDialog(self.root, row["project_name"], start)
        if dlg.result is None:
            return
        self._guard(lambda: db_logic.set_active_start_time(dlg.result),
                    "Could not adjust the start time")
        self.refresh(reschedule=False)

    def on_discard(self):
        active = db_logic.get_active_timer()
        paused = None if active else paused_row()
        row = active or paused
        if not row:
            Notice(self.root, "Nothing running", "There's no timer to discard.")
            return
        start = datetime.datetime.fromisoformat(row["start_time"])
        elapsed = fmt_elapsed(datetime.datetime.now() - start)
        dlg = ConfirmDialog(
            self.root, "Discard this timer?",
            f"{row['project_name']} — {elapsed} since {start:%-I:%M %p}.\n\n"
            f"The entry is deleted and nothing is logged. This can't be undone.",
            confirm="Discard")
        if not dlg.result:
            return
        removed = []
        if self._guard(lambda: removed.append(db_logic.discard_active_timer()),
                       "Could not discard the timer"):
            if removed and removed[0]:
                Notice(self.root, "Timer discarded", "Nothing was logged.")
            else:
                Notice(self.root, "Nothing to discard",
                       "The timer had already been saved or removed.")
        self.refresh(reschedule=False)

    def on_log_hours(self):
        dlg = LogHoursDialog(self.root, self.projects)
        if dlg.result is None:
            return
        project, hours, desc = dlg.result
        if self._guard(lambda: db_logic.add_manual_log(project, hours, desc),
                       "Could not save entry"):
            Notice(self.root, "Hours logged",
                   f"Added {hours}h to “{project}”, ending now.")
        self.refresh(reschedule=False)

    def on_close(self):
        # An unfinished timer is the one thing worth interrupting a quit for:
        # it is still in the database, but nothing has been logged yet.
        active = db_logic.get_active_timer()
        paused = None if active else paused_row()
        row = active or paused
        if row:
            start = datetime.datetime.fromisoformat(row["start_time"])
            state = "running" if active else "paused"
            choice = ChoiceDialog(
                self.root, "A timer is still going",
                f"{row['project_name']} — {fmt_elapsed(datetime.datetime.now() - start)} "
                f"{state} since {start:%-I:%M %p}, not yet saved as an entry.\n\n"
                f"Leaving it keeps it {state}; it will still be there next time.",
                [("Leave it " + state, "leave", "primary"),
                 ("Stop and save it now", "save", "secondary"),
                 ("Discard it — log nothing", "discard", "danger")],
                height=320)
            if choice.result is None:
                return                      # dismissed: don't quit
            if choice.result == "save":
                self.on_stop()
                if db_logic.get_active_timer() or paused_row():
                    return                  # they backed out of the stop dialog
            elif choice.result == "discard":
                self._guard(db_logic.discard_active_timer,
                            "Could not discard the timer")

        # Cancel queued callbacks first: one firing after destroy() raises a
        # Tcl "invalid command name" on the way out.
        for job in (self._poll_job, self._resize_job):
            if job:
                try:
                    self.root.after_cancel(job)
                except tk.TclError:
                    pass
        self._poll_job = self._resize_job = None
        self.settings["geometry"] = self.root.winfo_geometry()
        save_settings(self.settings)
        self.root.destroy()


if __name__ == "__main__":
    set_mac_app_name()   # must precede Tk(), which builds the menu bar
    root = tk.Tk()
    app = TimerApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
