#!/usr/bin/env python3
"""Publish bounded, attributed Riftbound snapshots using only documented public reads.

No third-party packages, website scraping, private/staff endpoints, or keys in output.
TopDeck API reference: https://topdeck.gg/docs/tournaments-v2
"""
import argparse
import collections
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request

SCHEMA = 1
MAX_PACK = 2 * 1024 * 1024
MAX_TOTAL = 20 * 1024 * 1024
API_LIMIT = 12 * 1024 * 1024
ID = re.compile(r"[A-Za-z0-9._:-]{1,120}\Z")
TOPDECK = {"id": "topdeck", "name": "TopDeck.gg", "url": "https://topdeck.gg",
           "attribution": "Tournament data provided by TopDeck.gg."}
FORMATS = {"Constructed", "Limited", "Sealed", "2v2", "Free-for-All"}
SECTIONS = {"legend": "Legend", "legends": "Legend", "commander": "Legend",
            "commanders": "Legend", "champion": "Champion", "chosenchampion": "Champion",
            "maindeck": "MainDeck", "mainboard": "MainDeck", "main": "MainDeck",
            "sideboard": "Sideboard", "side": "Sideboard", "runes": "Runes", "rune": "Runes",
            "battlefields": "Battlefields", "battlefield": "Battlefields",
            "additionallegends": "AdditionalLegends", "extralegends": "AdditionalLegends"}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def text(value, cap=200):
    if value is None:
        return ""
    value = str(value).strip()
    if len(value) > cap or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ValueError("Invalid text field")
    return value


def identifier(value):
    value = text(value, 120)
    if not ID.fullmatch(value):
        raise ValueError("Invalid record identifier")
    return value


def https(value, required=False):
    value = text(value, 2000)
    parsed = urllib.parse.urlsplit(value)
    if value and (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password):
        raise ValueError("Invalid HTTPS source URL")
    if required and not value:
        raise ValueError("Missing source URL")
    return value


def timestamp(value):
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return dt.datetime.fromisoformat(text(value).replace("Z", "+00:00")).astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def encoded(data):
    return (json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def bounded_read(response, cap):
    if int(response.headers.get("Content-Length", "0")) > cap:
        raise ValueError("Response too large")
    value = response.read(cap + 1)
    if len(value) > cap:
        raise ValueError("Response too large")
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A provider redirect must never forward the Authorization header to another host.
        return None


def recent(value, seconds):
    try:
        return time.time() - dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() < seconds
    except (ValueError, TypeError):
        return False


class TopDeckClient:
    """One combined rolling budget for every request, including retries and discovery."""
    def __init__(self, key, deadline=None, previous_calls=()):
        self.key = key
        offset = time.monotonic() - time.time()
        self.calls = collections.deque(float(value) + offset for value in previous_calls[-6:] if isinstance(value, (int, float)) and time.time() - value < 60.05)
        self.deadline = deadline
        self.opener = urllib.request.build_opener(NoRedirect())

    def request_times(self):
        offset = time.time() - time.monotonic()
        return [round(value + offset, 3) for value in self.calls][-6:]

    def request(self, path, payload=None):
        if not path.startswith("/v2/tournaments") or "?" in path:
            raise ValueError("Only documented public tournament endpoints are permitted")
        for attempt in range(3):
            current = time.monotonic()
            while self.calls and current - self.calls[0] >= 60.05:
                self.calls.popleft()
            spacing = self.calls[-1] + 10.05 - current if self.calls else 0
            window = self.calls[0] + 60.05 - current if len(self.calls) >= 6 else 0
            wait = max(0, spacing, window)
            if self.deadline is not None and current + wait >= self.deadline:
                raise TimeoutError("Collector time limit reached")
            if wait:
                time.sleep(wait)
            self.calls.append(time.monotonic())
            body = encoded(payload) if payload is not None else None
            request = urllib.request.Request("https://topdeck.gg/api" + path, body,
                headers={"Authorization": self.key, "Accept": "application/json",
                         "Content-Type": "application/json", "User-Agent": "RiftboundCommunitySnapshots/1"})
            try:
                with self.opener.open(request, timeout=25) as response:
                    return json.loads(bounded_read(response, API_LIMIT))
            except urllib.error.HTTPError as error:
                if error.code not in (429, 502, 503, 504) or attempt == 2:
                    # Do not print request objects, bodies or authentication headers.
                    raise RuntimeError("TopDeck returned HTTP " + str(error.code)) from None
                retry = error.headers.get("Retry-After", "")
                try:
                    delay = float(retry)
                except ValueError:
                    try:
                        import email.utils
                        delay = email.utils.parsedate_to_datetime(retry).timestamp() - time.time()
                    except (ValueError, TypeError):
                        delay = 30 * (attempt + 1)
                delay = max(10.05, min(delay, 180))
                if self.deadline is not None and time.monotonic() + delay >= self.deadline:
                    raise TimeoutError("Collector time limit reached") from None
                time.sleep(delay)


def previous_snapshot(base, skip_load=None):
    """Recover only declared, hashed packs from the configured GitHub Pages origin."""
    base = https(base, True).rstrip("/") + "/"
    parsed = urllib.parse.urlsplit(base)
    if not parsed.hostname.endswith(".github.io") or parsed.query or parsed.fragment:
        raise ValueError("Published base must be a GitHub Pages HTTPS URL")
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(base + "community/manifest.json", timeout=20) as response:
            manifest = json.loads(bounded_read(response, MAX_PACK))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None, [], [], []
        raise RuntimeError("Published manifest returned HTTP " + str(error.code)) from None
    if manifest.get("schema_version") != SCHEMA or len(manifest.get("packs", [])) > 150:
        raise ValueError("Unsupported published manifest")
    if skip_load and skip_load(manifest):
        return manifest, None, None, None
    total = 0
    decks, events = {}, {}
    sources = {identifier(s["id"]): s for s in manifest.get("sources", [])}
    for pack in manifest.get("packs", []):
        path = pack["path"]
        if not re.fullmatch(r"packs/[A-Za-z0-9._/-]+\.json", path) or ".." in path:
            raise ValueError("Invalid published pack path")
        size = int(pack["bytes"])
        total += size
        if not 0 < size <= MAX_PACK or total > MAX_TOTAL:
            raise ValueError("Published feed exceeds bounded download size")
        with opener.open(base + "community/" + path, timeout=20) as response:
            body = bounded_read(response, MAX_PACK)
        if len(body) != size or hashlib.sha256(body).hexdigest() != pack["sha256"]:
            raise ValueError("Published pack integrity mismatch")
        data = json.loads(body)
        if data.get("schema_version") != SCHEMA:
            raise ValueError("Unsupported published pack")
        for source in data.get("sources", []):
            sources[identifier(source["id"])] = source
        for entry in data.get("decks", []):
            decks[identifier(entry["id"])] = entry
        for entry in data.get("events", []):
            events[identifier(entry["id"])] = entry
    return manifest, list(decks.values()), list(events.values()), list(sources.values())


def preserve_updated(record, previous, collected_at, fetched=True):
    old = previous.get(record["id"])
    comparable = dict(record)
    if old and {k: v for k, v in old.items() if k not in ("updated_at", "fetched_at")} == comparable:
        record["updated_at"] = old.get("updated_at", collected_at)
    else:
        record["updated_at"] = collected_at
    record["fetched_at"] = collected_at if fetched or not old else old.get("fetched_at", old.get("updated_at", collected_at))
    return record


def event_from_info(info, tid, collected_at, previous, complete=False):
    location = info.get("location") or info.get("eventData") or {}
    return preserve_updated({"id": identifier("topdeck:" + tid), "source_id": "topdeck",
        "name": text(info.get("name") or info.get("tournamentName")),
        "start_at": timestamp(info.get("startDate")), "end_at": timestamp(info.get("endDate")),
        "city": text(location.get("city")), "country": text(location.get("country")),
        # Provider title is not evidence of an official competitive tier.
        "event_type": "Tournament", "format": text(info.get("format")),
        "status": "Complete" if complete else text(info.get("status")),
        "url": "https://topdeck.gg/event/" + urllib.parse.quote(tid, safe=""),
        "coverage_urls": [], "matches": []}, previous, collected_at)


def structured_text(obj):
    if not isinstance(obj, dict) or len(obj) > 20:
        return ""
    result = []
    for label, cards in obj.items():
        section = SECTIONS.get(re.sub(r"[^a-z]", "", str(label).lower()))
        if section is None or not isinstance(cards, dict) or len(cards) > 200:
            return ""  # Unknown sections remain available at the original source.
        result.append(section)
        for name, value in cards.items():
            # The documented map-of-name-to-quantity shape; never guess nested objects.
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1000:
                return ""
            name = text(name)
            if not name or "\n" in name:
                return ""
            result.append(str(value) + " " + name)
        result.append("")
    return "\n".join(result).strip()


def plain_text(value):
    """Normalize only named sections plus quantity/name lines; never ingest HTML."""
    if not isinstance(value, str) or len(value) > 100000:
        return ""
    result, section = [], None
    for line in value.splitlines():
        line = line.strip()
        if not line:
            continue
        key = re.sub(r"[^a-z]", "", line.lower())
        if key in SECTIONS:
            section = SECTIONS[key]
            result += ["", section]
            continue
        match = re.fullmatch(r"(\d{1,3})\s*[xX]?\s+(.{1,200})", line)
        if not match or "<" in line or ">" in line:
            return ""
        if section is None:
            return ""  # No guessing whether unsectioned legends belong to the draw pile.
        qty = int(match[1])
        if qty < 1:
            return ""
        result.append(str(qty) + " " + text(match[2]))
    return "\n".join(result).strip()


def deck_from_player(player, tid, fmt, collected_at, previous):
    list_value = player.get("decklist")
    raw = structured_text(player.get("deckObj")) or plain_text(list_value)
    code = ""
    if isinstance(list_value, str) and re.fullmatch(r"[A-Z2-7]{16,16384}=*", list_value.strip(), re.I):
        code = list_value.strip().rstrip("=")
    link = ""
    if isinstance(list_value, str) and list_value.strip().startswith("https://"):
        link = https(list_value)
    # A public URL is a link, never permission to crawl its host.
    if not raw and not code and not link and not player.get("leader"):
        return None
    player_id = text(player.get("id"), 100)
    if not player_id or not ID.fullmatch(player_id):
        player_id = hashlib.sha256(text(player.get("name")).encode()).hexdigest()[:20]
    legend = text(player.get("leader"))
    champion = ""
    if raw:
        in_champion = False
        for line in raw.splitlines():
            if line == "Champion":
                in_champion = True
            elif in_champion and re.match(r"\d+ ", line):
                champion = line.split(" ", 1)[1]
                break
            elif line and not re.match(r"\d+ ", line):
                in_champion = False
    creator = text(player.get("name"))
    return preserve_updated({"id": identifier("topdeck:" + tid + ":" + player_id), "source_id": "topdeck",
        "name": text((legend or "Riftbound") + " · " + creator), "creator": creator,
        "legend": legend, "champion": champion, "format": fmt, "event_id": "topdeck:" + tid,
        "url": link or "https://topdeck.gg/event/" + urllib.parse.quote(tid, safe=""),
        "deck_code": code, "raw_text": raw}, previous, collected_at)


def matches_from_tables(tables):
    if not isinstance(tables, list) or len(tables) > 500:
        raise ValueError("Too many public tables")
    result = []
    for table in tables:
        players = table.get("players") or []
        if len(players) > 10:
            continue
        winner = text(table.get("winner"))
        status = text(table.get("status"))
        score = ""
        if isinstance(table.get("winner_games"), int) and isinstance(table.get("loser_games"), int):
            score = " (" + str(table["winner_games"]) + "–" + str(table["loser_games"]) + ")"
        outcome = winner + score if winner else ("Draw" if table.get("winner_id") == "Draw" else "")
        result.append({"table": text(table.get("table")), "players": [text(p.get("name"), 100) for p in players],
                       "result": outcome, "status": status})
    return result


def curated_records(config, collected_at, previous_decks, previous_events):
    sources = []
    for source in config.get("sources", []):
        sources.append({"id": identifier(source["id"]), "name": text(source["name"]),
            "url": https(source["url"], True), "attribution": text(source["attribution"], 500)})
    allowed = {s["id"] for s in sources}
    events, decks = [], []
    for supplied in config.get("events", []):
        if supplied["source_id"] not in allowed:
            raise ValueError("Curated event needs declared source attribution")
        record = {key: text(supplied.get(key)) for key in
            ("name", "source_id", "city", "country", "event_type", "format", "status")}
        record.update(id=identifier(supplied["id"]), url=https(supplied["url"], True),
            start_at=timestamp(supplied.get("start_at")), end_at=timestamp(supplied.get("end_at")),
            coverage_urls=[https(v, True) for v in supplied.get("coverage_urls", [])][:10], matches=[])
        events.append(preserve_updated(record, previous_events, collected_at, fetched=False))
    for supplied in config.get("decks", []):
        if supplied["source_id"] not in allowed or not supplied.get("redistribution_permission"):
            raise ValueError("Curated decks need attribution and recorded redistribution permission")
        record = {key: text(supplied.get(key)) for key in
            ("name", "source_id", "creator", "legend", "champion", "format", "event_id")}
        record.update(id=identifier(supplied["id"]), url=https(supplied["url"], True),
            deck_code=text(supplied.get("deck_code"), 16384), raw_text=plain_text(supplied.get("raw_text", "")))
        decks.append(preserve_updated(record, previous_decks, collected_at, fetched=False))
    return sources, decks, events


def write_feed(out, sources, decks, events, collected_at, state, warnings, config_hash):
    out.mkdir(parents=True, exist_ok=True)
    pack_dir = out / "packs"
    pack_dir.mkdir(exist_ok=True)
    packs = []
    total = 0

    def save(pack_id, title, kind, pack_decks, pack_events):
        nonlocal total
        if len(packs) >= 150:
            raise ValueError("Too many packs")
        stamps = [e.get("fetched_at") or e.get("updated_at", "") for e in pack_decks + pack_events]
        pack_stamp = max(stamps, default=collected_at)
        data = {"schema_version": SCHEMA, "generated_at": pack_stamp, "sources": sources,
                "decks": pack_decks, "events": pack_events}
        body = encoded(data)
        if len(body) > MAX_PACK:
            raise ValueError("Pack exceeds 2 MB; decrease the configured event/deck limit")
        total += len(body)
        if total > MAX_TOTAL:
            raise ValueError("Feed exceeds the 20 MB download budget")
        path = "packs/" + pack_id + ".json"
        (out / path).write_bytes(body)
        packs.append({"id": pack_id, "title": title, "kind": kind, "path": path,
            "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
            "updated_at": pack_stamp})

    save("events", "Events and public results", "events", [], events[:1000])
    # Native app reads only selected packs. Event-only browsing does not download deck lists.
    for start in range(0, len(decks), 100):
        save("decks-" + str(start // 100 + 1), "Community decks " + str(start // 100 + 1), "decks", decks[start:start + 100], [])
    manifest = {"schema_version": SCHEMA, "generated_at": collected_at, "sources": sources,
                "packs": packs, "source_state": state, "warnings": warnings, "config_hash": config_hash}
    (out / "manifest.json").write_bytes(encoded(manifest))
    # Friendly Pages root rather than a blank/error page. No user data or tracking.
    (out.parent / "index.html").write_text('<!doctype html><meta charset="utf-8"><title>Riftbound community snapshots</title>'
        '<h1>Riftbound community snapshots</h1><p>Optional offline packs for the Riftbound app.</p>'
        '<p><a href="community/manifest.json">Snapshot manifest</a></p>'
        '<p>Data provided by <a href="https://topdeck.gg">TopDeck.gg</a>. '
        'Snapshots are not a live service. Source collection times are included with each record.</p>', encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("community_pipeline/sources.json"))
    parser.add_argument("--out", type=Path, default=Path("out/community"))
    parser.add_argument("--published-base", default="https://nowaddlearound.github.io/riftbound-decksapi/")
    parser.add_argument("--force", action="store_true", help="Force completed-event discovery before its daily interval")
    parser.add_argument("--live-minutes", type=int, default=0, help="Bounded collector, 0 or 1..60 minutes; output publishes only when it finishes")
    args = parser.parse_args()
    if not 0 <= args.live_minutes <= 60:
        parser.error("live-minutes must be between 0 and 60")
    config_bytes = args.config.read_bytes()
    config = json.loads(config_bytes)
    config_hash = hashlib.sha256(config_bytes).hexdigest()
    formats = config.get("topdeck", {}).get("formats", ["Constructed"])
    if len(formats) > 5 or any(f not in FORMATS for f in formats):
        raise ValueError("Use documented Riftbound formats")
    tracked = config.get("topdeck", {}).get("tracked_tournaments", [])
    if len(tracked) > 6:
        raise ValueError("At most six tracked tournament IDs keeps each scheduled job bounded")
    collected_at = now()
    # Failure recovering an existing feed must stop publication rather than erase last-good data.
    def no_work(manifest):
        state = manifest.get("source_state", {})
        return not args.force and not args.live_minutes and not tracked and manifest.get("config_hash") == config_hash and all(recent(state.get("topdeck:" + fmt), 86400) for fmt in formats)
    previous, old_decks, old_events, old_sources = previous_snapshot(args.published_base, no_work)
    if old_decks is None:
        print("Daily discovery is current and no tournaments are tracked. Unchanged; skipping pack downloads and Pages deployment.")
        return 100
    decks = {e["id"]: e for e in old_decks}
    events = {e["id"]: e for e in old_events}
    sources = {s["id"]: s for s in old_sources}
    source_state = (previous or {}).get("source_state", {})
    warnings = []
    curated_sources, curated_decks, curated_events = curated_records(config, collected_at, decks, events)
    sources.update({s["id"]: s for s in curated_sources})
    decks.update({d["id"]: d for d in curated_decks})
    events.update({e["id"]: e for e in curated_events})
    key = os.environ.get("TOPDECK_API_KEY", "").strip()
    if key:
        sources[TOPDECK["id"]] = TOPDECK
        client = TopDeckClient(key, previous_calls=source_state.get("request_times", []))
        days = max(1, min(int(config.get("topdeck", {}).get("days_back", 14)), 90))
        for fmt in formats:
            if not args.force and (previous or {}).get("config_hash") == config_hash and recent(source_state.get("topdeck:" + fmt), 86400):
                continue
            try:
                response = client.request("/v2/tournaments", {"game": "Riftbound", "format": fmt, "last": days,
                    "columns": ["name", "id", "decklist"], "rounds": False})
                if not isinstance(response, list):
                    raise ValueError("Unexpected bulk tournament response")
                shapes = collections.Counter()
                for tournament in response[:200]:
                    if tournament.get("game") != "Riftbound":
                        continue
                    tid = identifier(tournament["TID"])
                    event = event_from_info(tournament, tid, collected_at, events, complete=True)
                    events[event["id"]] = event
                    for player in tournament.get("standings", [])[:1000]:
                        shapes["players"] += 1
                        shapes["decklist:" + type(player.get("decklist")).__name__] += 1
                        shapes["deckObj:" + type(player.get("deckObj")).__name__] += 1
                        try:
                            deck = deck_from_player(player, tid, fmt, collected_at, decks)
                            if deck:
                                decks[deck["id"]] = deck
                                shapes["supported_exports" if deck["raw_text"] or deck["deck_code"] else "source_links"] += 1
                        except (ValueError, TypeError, KeyError):
                            continue
                source_state["topdeck:" + fmt] = collected_at
                # Shape/count diagnostics only; never raw responses, player values or headers.
                print("TopDeck", fmt, "public export availability:", json.dumps(dict(shapes), sort_keys=True))
                if len(response) > 200:
                    warnings.append("The configured TopDeck query returned more than 200 events; this bounded feed includes the first 200.")
            except (OSError, RuntimeError, ValueError, KeyError) as error:
                warnings.append("TopDeck " + fmt + " could not update; last-good records were kept (" + type(error).__name__ + ").")
        live_ids = []
        for supplied in tracked:
            tid = identifier(supplied)
            try:
                event_id = "topdeck:" + tid
                event = events.get(event_id)
                if event is None or args.force or not recent(source_state.get("topdeck:info:" + tid), 900):
                    info = client.request("/v2/tournaments/" + urllib.parse.quote(tid, safe="") + "/info")
                    if info.get("game") != "Riftbound":
                        continue
                    event = event_from_info(info, tid, now(), events)
                    event["matches"] = events.get(event_id, {}).get("matches", [])
                    events[event_id] = event
                    source_state["topdeck:info:" + tid] = event["fetched_at"]
                if event.get("status") == "Ongoing":
                    live_ids.append(tid)
                    tables = client.request("/v2/tournaments/" + urllib.parse.quote(tid, safe="") + "/rounds/latest")
                    event = dict(event)
                    event["matches"] = matches_from_tables(tables)
                    event["updated_at"] = event["fetched_at"] = now()
                    events[event_id] = event
                    source_state["topdeck:rounds:" + tid] = event["fetched_at"]
            except (OSError, RuntimeError, ValueError, KeyError):
                warnings.append("A tracked TopDeck event could not update; last-good records were kept.")
        if args.live_minutes and live_ids:
            client.deadline = time.monotonic() + args.live_minutes * 60
            n = 0
            while time.monotonic() < client.deadline:
                tid = live_ids[n % len(live_ids)]
                n += 1
                try:
                    tables = client.request("/v2/tournaments/" + urllib.parse.quote(tid, safe="") + "/rounds/latest")
                    event = dict(events["topdeck:" + tid])
                    event["matches"] = matches_from_tables(tables)
                    event["updated_at"] = now()
                    event["fetched_at"] = event["updated_at"]
                    events[event["id"]] = event
                    source_state["topdeck:rounds:" + tid] = event["updated_at"]
                except TimeoutError:
                    break
                except (OSError, RuntimeError, ValueError, KeyError):
                    warnings.append("Public round collection failed; the last successful round was kept.")
                    break
        elif args.live_minutes:
            warnings.append("No configured tracked Riftbound event is currently ongoing. No live tables were collected.")
        source_state["request_times"] = client.request_times()
    else:
        warnings.append("TOPDECK_API_KEY is not configured; only curated and last-good snapshots are included.")
    # Preserve a finite local corpus and keep new entries first; no derived meta rankings.
    excluded_decks = {identifier(v) for v in config.get("exclude_deck_ids", [])}
    excluded_events = {identifier(v) for v in config.get("exclude_event_ids", [])}
    all_decks = sorted((d for d in decks.values() if d["id"] not in excluded_decks and d.get("event_id") not in excluded_events),
        key=lambda d: (d.get("updated_at", ""), d["id"]), reverse=True)[:1000]
    all_events = sorted((e for e in events.values() if e["id"] not in excluded_events),
        key=lambda e: (e.get("start_at", ""), e["id"]), reverse=True)[:1000]
    used = {entry["source_id"] for entry in all_decks + all_events}
    if key:
        used.add("topdeck")
    source_list = [source for source in sources.values() if source["id"] in used]
    if previous and old_decks == all_decks and old_events == all_events and old_sources == source_list and previous.get("source_state") == source_state and previous.get("warnings", []) == sorted(set(warnings)) and previous.get("config_hash") == config_hash:
        print("Source data unchanged; skipping Pages deployment.")
        return 100
    write_feed(args.out, source_list, all_decks, all_events, now(), source_state, sorted(set(warnings)), config_hash)
    print("Prepared", len(all_decks), "public deck links/lists and", len(all_events), "events.")
    for warning in sorted(set(warnings)):
        print(warning)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
