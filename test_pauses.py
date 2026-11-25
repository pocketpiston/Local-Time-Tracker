"""Pause/resume must count only worked periods, never the break.

Runs against a throwaway copy of the schema with a pinned clock, so the real
time_tracker.db is never touched:

    python3 -m unittest test_pauses -v
"""
import datetime as dt
import os
import tempfile
import unittest

import db_logic
import generate_invoice

D = dt.date(2026, 11, 25)


def at(hhmm, day=D):
    h, m = map(int, hhmm.split(":"))
    return dt.datetime.combine(day, dt.time(h, m))


class PauseTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._orig = (db_logic.DB_NAME, db_logic._now, generate_invoice.DB_PATH)
        db_logic.DB_NAME = self.path
        generate_invoice.DB_PATH = self.path
        db_logic.init_db()
        self.clock = at("00:00")
        db_logic._now = lambda: self.clock

    def tearDown(self):
        db_logic.DB_NAME, db_logic._now, generate_invoice.DB_PATH = self._orig
        os.remove(self.path)

    def tick(self, hhmm, day=D):
        self.clock = at(hhmm, day)

    # ── the reported scenario ───────────────────────────────────────
    def run_reported_scenario(self):
        self.tick("11:30"); db_logic.start_timer("LRTM")
        self.tick("12:00"); db_logic.stop_timer("[Paused]")        # pause
        self.tick("13:00"); db_logic.resume_paused_timer()          # resume
        self.tick("13:30")

    def test_running_after_resume_excludes_the_pause(self):
        self.run_reported_scenario()
        a = db_logic.get_active_timer()
        self.assertEqual(db_logic.worked_seconds(a["start_time"], self.clock, a["pauses"]),
                         3600)  # 30 min + 30 min, not 2 h
        self.assertEqual(db_logic.fmt_periods(a["start_time"], self.clock, a["pauses"]),
                         "11:30 AM–12:00 PM + 1:00 PM–1:30 PM")

    def test_saved_entry_and_invoice_exclude_the_pause(self):
        self.run_reported_scenario()
        db_logic.stop_timer("worked on it")
        rows = generate_invoice.fetch_entries(at("00:00", D.replace(day=1)),
                                              at("00:00", dt.date(2026, 12, 1)))
        self.assertEqual(len(rows), 1)
        _p, s, e, _d, pauses = rows[0]
        self.assertEqual((s, e), (at("11:30").isoformat(), at("13:30").isoformat()))
        self.assertEqual(db_logic.worked_seconds(s, e, pauses), 3600)
        lines = generate_invoice.aggregate_by_day(rows, at("00:00", D.replace(day=1)),
                                                  at("00:00", dt.date(2026, 12, 1)))
        self.assertEqual([l["hours"] for l in lines], [1.0])

    def test_paused_clock_shows_only_period_one(self):
        self.tick("11:30"); db_logic.start_timer("LRTM")
        self.tick("12:00"); db_logic.stop_timer("[Paused]")
        self.tick("12:45")
        p = db_logic.get_paused_timer()
        self.assertEqual(db_logic.worked_seconds(p["start_time"], p["end_time"], p["pauses"]),
                         1800)

    def test_stop_while_paused_keeps_earlier_breaks(self):
        self.run_reported_scenario()                       # break 12:00–13:00
        self.tick("14:00"); db_logic.stop_timer("[Paused]")  # second pause
        self.tick("15:00")
        p = db_logic.get_paused_timer()
        db_logic.update_last_entry("done")
        # 11:30–12:00 + 13:00–14:00 = 1.5 h; the open 14:00 pause is outside the entry
        self.assertEqual(db_logic.worked_seconds(p["start_time"], p["end_time"], p["pauses"]),
                         5400)

    def test_many_cycles(self):
        self.tick("09:00"); db_logic.start_timer("X")
        for pause, resume in (("09:10", "09:20"), ("09:30", "10:00"), ("10:15", "10:16")):
            self.tick(pause); db_logic.stop_timer("[Paused]")
            self.tick(resume); db_logic.resume_paused_timer()
        self.tick("11:00"); db_logic.stop_timer("x")
        with db_logic.get_db() as (_c, cur):
            cur.execute("SELECT id, start_time, end_time FROM time_logs")
            i, s, e = cur.fetchone()
        # 2 h span − (10 + 30 + 1) min of breaks = 79 min
        self.assertEqual(db_logic.worked_seconds(s, e, db_logic.get_pauses(i)), 79 * 60)

    def test_discard_removes_its_pauses(self):
        self.run_reported_scenario()
        db_logic.discard_active_timer()
        self.assertEqual(db_logic.pauses_by_log(), {})

    # ── pure helpers ────────────────────────────────────────────────
    def test_pauses_are_clipped_to_corrected_range(self):
        pauses = [(at("12:00"), at("13:00"))]
        # end corrected to before the break ended: only the in-range part is cut
        self.assertEqual(db_logic.worked_seconds(at("11:30"), at("12:30"), pauses), 1800)
        # start corrected to after the break: the break no longer applies
        self.assertEqual(db_logic.worked_seconds(at("13:10"), at("13:30"), pauses), 1200)

    def test_typed_duration_skips_pauses(self):
        pauses = [(at("12:00"), at("13:00"))]
        self.assertEqual(db_logic.end_for_worked(at("11:30"), 1.0, pauses), at("13:30"))
        self.assertEqual(db_logic.end_for_worked(at("11:30"), 0.25, pauses), at("11:45"))

    def test_entry_without_pauses_is_unchanged(self):
        self.assertEqual(db_logic.worked_seconds(at("09:00"), at("10:30")), 5400)

    def test_overnight_pause_splits_by_day(self):
        nxt = D + dt.timedelta(days=1)
        shares = generate_invoice.worked_by_day(
            at("22:00"), at("02:00", nxt), [(at("23:00"), at("01:00", nxt))])
        self.assertEqual(shares, [(D, 1.0), (nxt, 1.0)])


if __name__ == "__main__":
    unittest.main()
