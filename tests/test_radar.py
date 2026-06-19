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


class WixEventsTests(unittest.TestCase):
    """Offline parse of an embedded Wix-warmup events payload."""

    FIXTURE = (
        '<html><body>'
        '<script id="wix-warmup-data" type="application/json">'
        '{"appsWarmupData":{"app":{"w":{"events":{"events":[{'
        '"title":"Osaka Language Exchange 国際交流",'
        '"slug":"osaka-language-exchange",'
        '"siteEventPageUrl":"/events/osaka-language-exchange",'
        '"scheduling":{"config":{"startDate":"2026-07-01T10:00:00.000Z",'
        '"endDate":"2026-07-01T12:00:00.000Z","scheduleTbd":false}},'
        '"location":{"name":"Umeda Hall",'
        '"fullAddress":"Osaka, Kita Ward, Umeda",'
        '"coordinates":{"lat":34.7055,"lng":135.4983}},'
        '"description":"Meet locals and practise."}]}}}}}'
        '</script></body></html>'
    )

    def test_parses_wix_warmup_events(self):
        import json
        import re

        from radar.sources import wixevents

        blob = re.search(
            r'id="wix-warmup-data"[^>]*>(.*?)</script>', self.FIXTURE, re.DOTALL
        ).group(1)
        evs = wixevents._find_events(json.loads(blob)["appsWarmupData"])
        self.assertEqual(len(evs), 1)
        ev = wixevents._to_event(evs[0], "https://example.com")
        self.assertIsNotNone(ev)
        self.assertEqual(ev.lat, 34.7055)
        self.assertEqual(ev.url, "https://example.com/events/osaka-language-exchange")
        score_event(ev, CFG)
        self.assertIn("language_exchange", ev.matched)


class _FakeTG:
    """Records outgoing calls; feeds a fixed set of updates once."""

    def __init__(self, updates):
        self._updates = updates
        self.sent = []
        self.answered = []

    def set_my_commands(self, commands):
        pass

    def get_updates(self, offset=0, timeout=0):
        out, self._updates = self._updates, []
        return out

    def send_message(self, text, chat_id=None, disable_preview=True, reply_markup=None):
        self.sent.append((text, reply_markup))

    def answer_callback_query(self, callback_id, text=""):
        self.answered.append(text)


def _state():
    from pathlib import Path

    from radar.state import State

    return State(
        {
            "version": 1,
            "events": {},
            "geocode_cache": {},
            "going": {},
            "telegram_offset": 0,
            "last_digest_date": None,
            "last_run_utc": None,
        },
        Path("/tmp/_radar_test_state.json"),
    )


class CollectGatingTests(unittest.TestCase):
    def test_should_collect_respects_interval(self):
        from radar.pipeline import _should_collect

        st = _state()
        now = datetime.now(TZ)
        # No prior collection -> collect.
        self.assertTrue(_should_collect(CFG, st, now, force=False))
        # Just collected -> skip until interval elapses.
        st.last_collect_utc = now.isoformat()
        self.assertFalse(_should_collect(CFG, st, now, force=False))
        # force always collects.
        self.assertTrue(_should_collect(CFG, st, now, force=True))
        # After the interval, collect again.
        later = now + timedelta(minutes=CFG.collect_interval_min + 1)
        self.assertTrue(_should_collect(CFG, st, later, force=False))


class InteractivityTests(unittest.TestCase):
    def test_bottom_button_label_maps_to_command(self):
        from radar.messages import LABEL_TO_COMMAND

        self.assertEqual(LABEL_TO_COMMAND["🕌 Halal"], "halal")
        self.assertEqual(LABEL_TO_COMMAND["📅 Hoy"], "hoy")

    def test_event_inline_keyboard_has_voy(self):
        from radar.messages import event_inline_keyboard

        e = _evt("Test", url="https://x.com")
        kb = event_inline_keyboard(e, "https://maps")
        datas = [b.get("callback_data") for b in kb["inline_keyboard"][0]]
        self.assertIn(f"voy:{e.id}", datas)

    def test_hoy_button_tap_lists_today(self):
        from radar.commands import process_commands

        today = datetime.now(TZ)
        e = score_event(_evt("国際交流パーティー", start_dt=today), CFG)
        update = {"update_id": 1, "message": {"text": "📅 Hoy", "chat": {"id": 9}, "from": {"id": 1}}}
        tg = _FakeTG([update])
        process_commands(tg, CFG, _state(), [e])
        joined = "\n".join(t for t, _ in tg.sent)
        self.assertIn("Eventos de hoy", joined)

    def test_voy_callback_marks_going(self):
        from radar.commands import process_commands

        e = score_event(_evt("国際交流", start_dt=datetime.now(TZ)), CFG)
        st = _state()
        update = {
            "update_id": 2,
            "callback_query": {
                "id": "cb1",
                "data": f"voy:{e.id}",
                "from": {"id": 7, "username": "luigi"},
                "message": {"chat": {"id": 9}},
            },
        }
        tg = _FakeTG([update])
        process_commands(tg, CFG, st, [e])
        self.assertEqual(st.going_count(e.id), 1)
        self.assertTrue(tg.answered)  # a toast was sent


if __name__ == "__main__":
    unittest.main(verbosity=2)
