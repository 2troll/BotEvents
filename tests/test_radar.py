"""Offline unit tests for the core, network-free logic.

Run with:  python -m unittest discover -s tests  (or: python -m pytest)
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from pathlib import Path

from radar.config import Config
from radar.dedupe import dedupe
from radar.messages import format_digest
from radar.telegram import _split_message
from radar.models import Event
from radar.reminders import due_reminders
from radar.scoring import is_relevant, score_event

CFG = Config.load(Path(__file__).resolve().parents[1] / "config.yaml")
TZ = CFG.tz


def _evt(title: str, **kw) -> Event:
    kw.setdefault("source", "test")
    return Event(title=title, **kw)


class ScoringTests(unittest.TestCase):
    def test_keyword_match_is_relevant(self):
        e = score_event(_evt("Osaka Hanabi 花火大会 Festival"), CFG)
        self.assertGreaterEqual(e.score, CFG.score_threshold)
        self.assertIn("fireworks", e.matched)
        self.assertTrue(is_relevant(e, CFG))

    def test_irrelevant_event_dropped(self):
        e = score_event(_evt("Quarterly accounting webinar"), CFG)
        self.assertFalse(is_relevant(e, CFG))

    def test_bilingual_japanese_keywords(self):
        e = score_event(_evt("国際交流パーティー in 京都"), CFG)
        self.assertIn("language_exchange", e.matched)

    def test_major_flag_from_category(self):
        e = score_event(_evt("淀川花火大会", attendee_count=100), CFG)
        self.assertTrue(e.major)

    def test_word_boundary_avoids_substring_false_positive(self):
        # "IT" must NOT match inside "kitchen"/"with"; "expo" must NOT match
        # "exponent". A plain food headline should not score as tech.
        e = score_event(_evt("New kitchen opens with limited seats"), CFG)
        self.assertNotIn("tech", e.matched)
        self.assertFalse(is_relevant(e, CFG))

    def test_word_boundary_still_matches_real_word(self):
        e = score_event(_evt("Osaka Tech Expo and startup hackathon"), CFG)
        self.assertIn("tech", e.matched)


class DedupeTests(unittest.TestCase):
    def test_same_event_collapses(self):
        day = datetime(2026, 7, 1, 18, 0)
        a = _evt("Tenjin Matsuri", start_dt=day, source="rss")
        b = _evt("Tenjin Matsuri!", start_dt=day, source="ical", venue="Osaka")
        out = dedupe([a, b])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].venue, "Osaka")  # richer record survives


class ReminderTests(unittest.TestCase):
    def test_intraday_fires_once(self):
        start = datetime.now(TZ) + timedelta(hours=2)
        e = score_event(_evt("Tech Meetup", start_dt=start), CFG)
        due = due_reminders([e], CFG)
        self.assertEqual(due, [(e, "intraday")])
        e.notified["intraday"] = True
        self.assertEqual(due_reminders([e], CFG), [])

    def test_major_advance_tiers(self):
        start = datetime.now(TZ) + timedelta(days=29)
        e = score_event(_evt("花火大会", start_dt=start), CFG)
        due = due_reminders([e], CFG)
        self.assertEqual(due[0][1], "d30")

    def test_past_event_no_reminder(self):
        start = datetime.now(TZ) - timedelta(hours=5)
        e = score_event(_evt("花火大会", start_dt=start), CFG)
        self.assertEqual(due_reminders([e], CFG), [])


class MessageTests(unittest.TestCase):
    def test_split_respects_limit(self):
        text = "\n".join(f"line {i}" for i in range(2000))
        chunks = _split_message(text, limit=500)
        self.assertTrue(all(len(c) <= 500 for c in chunks))
        self.assertGreater(len(chunks), 1)

    def test_digest_renders(self):
        e = score_event(_evt("花火大会", start_dt=datetime.now(TZ)), CFG)
        out = format_digest([e], CFG, map_url="https://example.com")
        self.assertIn("花火大会", out)
        self.assertIn("Kansai Radar", out)

    def test_digest_leads_section(self):
        lead = score_event(_evt("Osaka fireworks 花火 article", start_dt=None), CFG)
        out = format_digest([], CFG, leads=[lead])
        self.assertIn("New on the radar", out)
        self.assertIn("花火", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
