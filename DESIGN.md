# Desktop Timer Window — design notes

Why `timer_app.py` looks and behaves the way it does, what else was considered,
and which constraints are real rather than stylistic.

Visual drafts live on a design canvas:
<https://claude.ai/artifact/H9MUHZeUPYNpuqjYqoyFTr> (private to the repo owner).

---

## 1. The problem

The menu bar app (`menubar_app.py`) was often unreachable:

1. **The notch.** On a MacBook Pro 16", menu bar items that don't fit are hidden
   *behind* the notch. macOS does not overflow them into a scrollable list —
   they are simply gone.
2. **A wide title.** The app rendered `⏱️ LRTM (2h 15m)` — about 16 characters,
   permanently. Items lay out right-to-left, so the widest are clipped first.
3. **A menu bar manager.** Hidden Bar was already installed to ration space, and
   its toggle could tuck the tracker away too.

The brief was therefore *access that does not depend on menu bar space at all*.

## 2. Options considered

Before any visual work, five routes were weighed:

| | Approach | Verdict |
|---|---|---|
| A | Compact menu bar title (`⏱️2.3`) | Mitigates, doesn't fix — still menu-bar-bound |
| B | `tt` command-line interface | Strong, but terminal-only |
| C | Global hotkeys via Shortcuts.app | Strong; depends on B |
| D | Timer controls in the Streamlit dashboard | Needs a server running |
| E | Standalone desktop window | **Chosen** |

E won because the request was specifically for something *clickable* that shows
the timer. B + C remain the best follow-up if keyboard-speed access is wanted
later; they'd share the same database and need no changes here.

Within E, three toolkits were possible. **tkinter** was chosen over PyObjC and a
browser-based window because it is in the standard library — no new
dependencies — and verified working (Tk 8.6, with `-topmost` and alpha support).

## 3. Layout directions

Three were drawn and reviewed on the canvas:

- **A — Focus.** Clock as the single hero; project and totals recede. Calmest,
  fastest to read, shows least.
- **B — Panel.** Status in a state-tinted card, totals in a two-up card. More
  structure, more information. *Not chosen; kept on the canvas for reference.*
- **C — Compact bar.** 440×148 horizontal. Everything on one line.

**A and C were both wanted**, which produced the actual design: *one window with
a size breakpoint*, not two modes to switch between.

## 4. The responsive window

Short window packs `CompactView`, tall packs `ExpandedView`. Both read the same
state dict from `refresh()`, so behaviour cannot diverge between them. You can
drag the edge, or double-click the window background to snap between the two.

**Hysteresis, not a debounce.** The first build waited 120 ms after the last
resize event before swapping. It was correct and it felt broken: all the way
down a drag you watched the tall layout get squashed and clipped, and the swap
only landed once you released the mouse. It now swaps the moment a threshold is
crossed, with a dead zone so hovering on the edge doesn't flicker:

```
h < COLLAPSE_BELOW (250)   -> compact
h > EXPAND_ABOVE   (290)   -> expanded
in between                 -> keep whatever is showing
```

**A readiness gate** is still needed. While mapping, Tk reports transient
heights well under the real one; acting on those opened the window compact for
a beat on every launch, then snapped. `_on_map` waits for the window to settle.

**The double-click toggle binds to inert surfaces only** — frames and plain
labels, never the canvas buttons (a quick double-press of Stop would fire it)
and never entry fields (it would break double-click-to-select-a-word).

Window geometry and the always-on-top setting persist to
`.timer_app_settings.json`, so it reopens the way it was left.

## 5. Visual system

Deliberately small, and consistent with the Streamlit dashboard.

**Button colour is semantic.** Four options were drawn on the canvas and the
semantic one was chosen: green starts, amber holds, indigo finishes, red
destroys. One rule shaped all four — **Stop *saves* the entry, so red belongs
on Discard alone.** Colouring the button you press twenty times a day as a
hazard would teach you to hesitate over it.

| Tone | Fill | Text | Ratio |
|---|---|---|---|
| `go` — start / resume | `#0e7a55` | white | 5.34:1 |
| `hold` — pause | `#c07d0a` | ink | 5.23:1 |
| `finish` — stop and save | `#4453c4` | white | 6.40:1 |
| `danger` — discard | `#c02626` | white | 5.92:1 |
| `neutral` — cancel | `#e3e7ee` | ink | 12.4:1 |

Pause takes dark text rather than white. Amber is the one hue where white
cannot reach 4.5:1 without darkening into brown — the first attempt,
`#b5730a`, managed 3.87:1 — and a muddy Pause would have looked disabled
beside the others. Pause and Resume share a button, so it recolours with its
meaning.

Every button is one height (`BTN_H = 46`) and one label size. An earlier mix of
50 / 42 / 36 put different-sized buttons in rows directly above each other,
which read as misalignment.

**Colour** — the state is carried by hue *and* lightness, never hue alone:

| Token | Value | Use |
|---|---|---|
| `text` | `#15181f` | Primary text |
| `muted` | `#3f4554` | Labels, meta — 9.6:1 on white |
| `ghost` | `#9ba2af` | Idle clock: legible but clearly inactive |
| `accent` | `#4453c4` | Primary buttons |
| `running` | `#0e8a5f` | Running state |
| `paused` | `#c77a00` | Paused state |

The accent is a deepened version of the dashboard's `#5e72e4`. White text on the
original measures ~4.2:1, under the 4.5:1 threshold at button text size; the
darker tone clears it.

**Type** — Helvetica Neue for UI, Menlo for the clock. One hero, then labels,
then meta. Earlier drafts had too many intermediate steps, which is what made
the first build read as cluttered.

**Rhythm** — the running and idle states share an identical vertical rhythm, so
switching states swaps only *what sits in each slot* and nothing moves:

```
28  padding
20  status row      (dot + state)
18  →  13  PROJECT label
 7  →  44  project zone  (text when running, dropdown when idle)
12  →  46  clock
 5  →  19  meta line
20  →  46  primary action
```

The running state carries a redundant "PROJECT" label purely to hold that
alignment. It is the one piece of clutter accepted on purpose.

## 6. Custom widgets, and why

macOS ignores background colours on native `tk`/`ttk` buttons, so three controls
are drawn on canvases instead:

- **`Button`** — rounded, themeable, with hover and press states.
- **`Toggle`** — an iOS-style switch; clearer at a glance than a checkbox.
- **`Dropdown`** — replaces `tk_popup`, which renders the *native macOS context
  menu*: unstyleable, and positioned at the pointer rather than under the field.

Shapes are drawn as a 12-point control polygon with `smooth=True`. Replacing
that with mathematically exact arc points — 14 segments per corner, verified to
sit on the circle to within 0.000000px — looked **worse** and was reverted:
Tk's canvas antialiases a splined curve but not a raw polygon fill, so the
accurate version rendered with hard stair-stepped edges. Geometry is not the
constraint here; antialiasing is.

The dropdown needed three fixes that only appeared on screen:

1. A `Toplevel` is mapped the instant it is created, so macOS placed it at its
   own default spot before `geometry()` moved it. It now builds withdrawn, gets
   positioned, then `deiconify()` + `lift()`.
2. An `overrideredirect` window is given no focus, so the `<Escape>` binding
   never received a key event without `focus_force()`.
3. Rows use the field's own 13px text inset, so the list lines up under the text
   it replaces.

## 7. The stop dialog, and a billing correctness finding

The dialog shows **two** figures, not one:

```
This session     2:15:30        2.25 h
LRTM today       3.75 h    →    3.8 h billable
```

An early draft showed only a single `2.3 h billable` for the session. That is
**wrong**, and the database says so. `generate_invoice.py` buckets entries by
`(day, project, item_code)`, sums the raw hours, and *then* rounds up once:

```python
hours = math.ceil(b["hours"] * 10) / 10
```

Rounding each session separately gives every session its own ceiling. Measured
across the real database: **303.10 h vs 301.90 h — 1.2 hours over-counted** over
105 entries, with 23 days carrying more than one session on the same project.

So the app imports `classify` and the rounding rule *from the invoice script*
rather than reimplementing them, and `day_bucket()` mirrors the invoice's bucket
key. Verified: it matches `aggregate_by_day` exactly on every sampled bucket.

A second consequence is surfaced as a warning. The item code comes from
`classify(desc)` — keywords in the notes. So **what you type can split the day
into two buckets**, each rounding separately. When that is about to happen the
dialog says so.

A third only showed up on a later audit. `day_bucket()` originally attributed a
whole session to its start date, but the invoice **splits a session that runs
past midnight across both calendar days**, folding a spillover shorter than
`SPILLOVER_THRESHOLD_HOURS` back into the start day. The database holds five
such sessions, so the figure was wrong for every one of them. `day_shares()`
now reuses the invoice's own `split_by_calendar_day` and threshold rather than
approximating them, and the dialog names the day it is billing and explains the
spill. Verified against `aggregate_by_day` across 88 buckets over five months,
with no mismatches.

**The time is editable** because the database asked for it. Several entries carry
corrections written into the notes — *"Adjust to 2 hr 15 min for total session"*,
*"End time ~11:30 pm. Need to update hours."* Fixing it at the moment of
stopping stops it becoming a note-to-self.

## 8. Packaging

`build_app.sh` builds `Time Tracker.app` using only macOS's `sips`/`iconutil`,
so the Dock and menu bar show the project name and icon instead of "Python".

Two traps, both worth keeping in mind if the icon is ever replaced:

- `iconutil` accepts only the five base sizes (16/32/128/256/512 plus `@2x`).
  One invalid tile — `icon_64x64` — fails the entire set.
- `icon.png` is **actually a JPEG**. `sips` preserves the input format, so
  `-s format png` is required or every tile is a JPEG named `.png`, which
  `iconutil` rejects.

The bundle points back at the project folder, so code edits need no rebuild.

## 9. Known limitations

- **Always on top** keeps the window above other *windows*, but Tk does not
  expose macOS's "show on all Spaces" behaviour, so it will not follow you to
  another Space. Adding that needs PyObjC to set `collectionBehavior`.
- Tk cannot do rounded window corners or vibrancy; the frame stays square.
- The compact bar has no room for both totals and a full "Log hours" button, so
  the latter shrinks to an icon.
- The window polls the database once a second rather than watching it. Cheap at
  this size, but it is polling.

## 10. Testing notes

All database behaviour was exercised against **copies** of `time_tracker.db`,
never the live file. Worth repeating for future changes — `save_data` and the
stop paths both delete rows under some conditions.

The audit that followed the first build found six defects, of which two were
only observable on screen (dropdown placement, the startup layout flash). A
headless test that reads widget coordinates will pass while the window visibly
draws in the wrong place; screenshots caught what assertions could not.
