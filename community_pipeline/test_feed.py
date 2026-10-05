"""Local checks only: synthetic public fixtures, fake clock, no network or real keys."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

import build_feed as feed

STAMP = "2026-10-05T12:00:00Z"


class Response(io.BytesIO):
    def __init__(self, data=b"[]"):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


class Clock:
    def __init__(self):
        self.seconds = 1000.0
    def read(self):
        return self.seconds
    def sleep(self, seconds):
        self.seconds += seconds


class FeedChecks(unittest.TestCase):
    def setUp(self):
        # Resolve before registering recursive cleanup; every temporary path stays in this folder.
        self.directory = Path(__file__).resolve().parent
        self.temp = tempfile.TemporaryDirectory(prefix=".community-test-", dir=self.directory)
        self.root = Path(self.temp.name).resolve()
        self.assertEqual(self.root.parent, self.directory)
        self.addCleanup(self.temp.cleanup)

    def test_schema_hashes_and_attribution(self):
        event = feed.event_from_info({"name": "Fixture", "game": "Riftbound", "format": "Constructed",
            "startDate": 1780000000, "email": "PRIVATE", "discord": "PRIVATE"}, "fixture", STAMP, {}, True)
        feed.write_feed(self.root / "community", [feed.TOPDECK], [], [event], STAMP, {}, [], "fixture")
        manifest = json.loads((self.root / "community/manifest.json").read_text())
        pack = manifest["packs"][0]
        body = (self.root / "community" / pack["path"]).read_bytes()
        self.assertEqual(pack["bytes"], len(body))
        self.assertEqual(pack["sha256"], hashlib.sha256(body).hexdigest())
        data = json.loads(body)
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["events"][0]["source_id"], data["sources"][0]["id"])
        self.assertEqual(event["fetched_at"], STAMP)
        self.assertNotIn("PRIVATE", body.decode())

    def test_legend_and_event_packs_keep_original_records(self):
        event = feed.event_from_info({"name": "Fixture", "format": "Constructed", "startDate": 1780000000}, "fixture", STAMP, {}, True)
        deck = feed.deck_from_player({"id": "player", "name": "Public", "leader": "Ahri", "decklist": "https://example.org/deck"}, "fixture", "Constructed", STAMP, {})
        feed.write_feed(self.root / "community", [feed.TOPDECK], [deck], [event], STAMP, {}, [], "fixture")
        manifest = json.loads((self.root / "community/manifest.json").read_text())
        self.assertLessEqual(len(manifest["packs"]), 140)
        for prefix in ("legend-", "event-"):
            pack = next(pack for pack in manifest["packs"] if pack["id"].startswith(prefix))
            body = (self.root / "community" / pack["path"]).read_bytes()
            self.assertEqual(pack["sha256"], hashlib.sha256(body).hexdigest())
            self.assertEqual(json.loads(body)["decks"], [deck])
            self.assertEqual(json.loads(body)["decks"][0]["raw_text"], "")

    def test_only_supported_deck_shapes(self):
        self.assertEqual(feed.structured_text({"Legend": {"Fixture Legend": 1}, "MainDeck": {"Fixture Unit": 3}}),
                         "Legend\n1 Fixture Legend\n\nMainDeck\n3 Fixture Unit")
        self.assertEqual(feed.structured_text({"Unknown section": {"Fixture": 2}}), "")
        self.assertEqual(feed.structured_text({"MainDeck": {"Fixture": {"quantity": 2}}}), "")
        self.assertEqual(feed.plain_text("<html><body>not a deck</body></html>"), "")
        self.assertEqual(feed.plain_text("3 Unsectioned card"), "")

    def test_source_links_and_contact_exclusion(self):
        player = {"id": "public-player", "name": "Public display", "leader": "Fixture Legend",
                  "decklist": "https://example.org/public-export", "email": "private@example.org",
                  "discord": "private-contact", "staffNotes": "private-staff"}
        deck = feed.deck_from_player(player, "fixture", "Constructed", STAMP, {})
        self.assertEqual(deck["url"], player["decklist"])
        self.assertEqual(deck["raw_text"], "")
        self.assertEqual(deck["deck_code"], "")
        body = json.dumps(deck)
        for secret in ("private@example.org", "private-contact", "private-staff"):
            self.assertNotIn(secret, body)
        matches = feed.matches_from_tables([{"table": 1, "status": "Completed", "winner": "Public display",
            "players": [player], "discord": "private-contact", "staffNotes": "private-staff"}])
        self.assertEqual(matches[0]["players"], ["Public display"])
        self.assertNotIn("private", json.dumps(matches))

    def test_content_and_fetch_times_are_distinct(self):
        record = {"id": "fixture", "name": "same"}
        old = {"fixture": dict(record, updated_at="2026-10-04T12:00:00Z", fetched_at="2026-10-04T12:00:00Z")}
        updated = feed.preserve_updated(record, old, STAMP)
        self.assertEqual(updated["updated_at"], old["fixture"]["updated_at"])
        self.assertEqual(updated["fetched_at"], STAMP)

    def test_rate_spacing_and_shared_retry_budget(self):
        clock = Clock()
        requested = []
        class Opener:
            def open(self, request, timeout):
                requested.append(clock.read())
                self_outer.assertNotIn("view=staff", request.full_url)
                return Response()
        self_outer = self
        with patch.object(feed.time, "monotonic", clock.read), patch.object(feed.time, "time", clock.read), patch.object(feed.time, "sleep", clock.sleep):
            client = feed.TopDeckClient("SYNTHETIC_NOT_A_REAL_KEY")
            client.opener = Opener()
            for _ in range(8):
                client.request("/v2/tournaments/fixture/rounds/latest")
        self.assertTrue(all(b - a >= 10.049 for a, b in zip(requested, requested[1:])))
        self.assertTrue(all(requested[n + 6] - requested[n] >= 60.049 for n in range(len(requested) - 6)))
        attempts = []
        class RetryOpener:
            def open(self, request, timeout):
                attempts.append(clock.read())
                if len(attempts) == 1:
                    raise urllib.error.HTTPError(request.full_url, 429, "fixture", {"Retry-After": "20"}, None)
                return Response()
        with patch.object(feed.time, "monotonic", clock.read), patch.object(feed.time, "time", clock.read), patch.object(feed.time, "sleep", clock.sleep):
            client = feed.TopDeckClient("SYNTHETIC_NOT_A_REAL_KEY", previous_calls=requested[-6:])
            client.opener = RetryOpener()
            client.request("/v2/tournaments", {"game": "Riftbound", "format": "Constructed"})
        self.assertGreaterEqual(attempts[0] - requested[-1], 10.049)
        self.assertGreaterEqual(attempts[1] - attempts[0], 20)

    def test_missing_key_keeps_last_good_and_recovery_failure_stops_publish(self):
        config = self.root / "sources.json"
        config.write_text(json.dumps({"topdeck": {"formats": ["Constructed"], "tracked_tournaments": []}}))
        event = feed.event_from_info({"name": "Fixture", "format": "Constructed", "startDate": 1780000000}, "fixture", STAMP, {}, True)
        previous = {"schema_version": 1, "source_state": {}, "config_hash": "old"}
        args = ["build_feed.py", "--config", str(config), "--out", str(self.root / "community")]
        with patch.object(sys, "argv", args), patch.dict(os.environ, {"TOPDECK_API_KEY": ""}), \
                patch.object(feed, "previous_snapshot", return_value=(previous, [], [event], [feed.TOPDECK])), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(feed.main(), 0)
        manifest = json.loads((self.root / "community/manifest.json").read_text())
        data = json.loads((self.root / "community" / manifest["packs"][0]["path"]).read_text())
        self.assertEqual(data["events"], [event])
        self.assertTrue(manifest["warnings"])
        failed_out = self.root / "failed/community"
        args[-1] = str(failed_out)
        with patch.object(sys, "argv", args), patch.object(feed, "previous_snapshot", side_effect=RuntimeError("fixture recovery failure")):
            with self.assertRaises(RuntimeError):
                feed.main()
        self.assertFalse(failed_out.exists())


if __name__ == "__main__":
    unittest.main()
