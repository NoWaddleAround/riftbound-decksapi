# Riftbound community snapshots

Optional, free offline packs for the Android app. This repository uses the documented [TopDeck public API](https://topdeck.gg/docs/tournaments-v2), with visible attribution. It does not scrape other deck websites, mirror card artwork, upload personal collection data, or read staff-only/contact endpoints.

## Install in `nowaddlearound/riftbound-decksapi`

| Local file | Repository destination |
| --- | --- |
| `community_pipeline/build_feed.py` | `community_pipeline/build_feed.py` |
| `community_pipeline/sources.json` | `community_pipeline/sources.json` |
| `community_pipeline/test_feed.py` | `community_pipeline/test_feed.py` |
| `community_pipeline/community.yml` | `.github/workflows/community.yml` |
| `community_pipeline/README.md` | `README.md` |

1. Keep the repository public if using free public GitHub Actions runners and free Pages.
2. Set **Settings → Pages → Source → GitHub Actions**.
3. Set the repository Actions secret `TOPDECK_API_KEY` to the developer key. Never put it in source, URLs, the Android app, or JSON packs. The supplied workflow passes it only as a runner environment variable.
4. Run **Community snapshots** manually once. The schedule uses GitHub's lowest supported interval, every five minutes. Completed deck discovery still runs only once per day; tracked ongoing public rounds get one poll per scheduled run. With no tracked events and a current daily archive, a run fetches only the small manifest and exits unchanged. Schedule timing is inexact, and inactive public repository schedules can be disabled after 60 days. See [GitHub schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
5. The manifest becomes `https://nowaddlearound.github.io/riftbound-decksapi/community/manifest.json`. Prices remain in the independent `riftbound-prices` repository and are unaffected.

The first successful run may contain only source links if a public deck's export is a website URL. This is an honest availability limit: public access to a linked website is not permission to crawl it. No sample or fabricated deck/event data is published.

## Configure sources

`sources.json` starts with completed Riftbound Constructed events from the last 90 days, queried only once daily. Supported TopDeck formats are `Constructed`, `Limited`, `Sealed`, `2v2`, and `Free-for-All`. A request is made per selected format. The lookback can be 1–90 days.

`topdeck.tracked_tournaments` accepts up to six **real TopDeck tournament IDs** so every scheduled job remains bounded. Their public metadata is fetched separately at most every 15 minutes; ongoing public round tables are polled once per five-minute run. Upcoming events cannot be discovered by the completed-event search. Get IDs from an actual TopDeck event URL; a Zero/UVS event ID is not necessarily a TopDeck ID.

Manually curated calendars and authorized deck exports can be added through `sources`, `events`, and `decks`. Record source attribution and the original HTTPS URL. For deck records, `redistribution_permission` must document the actual author/operator grant; a nonempty value is an operator assertion, not an automatic permission check. Do not add scraped decks, paywalled exports, site comments, or graphics.

Calendar event fields:

```json
{
  "id": "provider:stable-event-id",
  "source_id": "provider",
  "name": "Verified event title",
  "url": "https://provider.example/events/original-id",
  "start_at": "2027-01-01T09:00:00Z",
  "end_at": "2027-01-01T19:00:00Z",
  "city": "City",
  "country": "Country",
  "event_type": "Provider event category",
  "format": "Constructed",
  "status": "Not Started",
  "coverage_urls": []
}
```

This example is a schema illustration only and is not included in the feed. Event categories are data, allowing official names to change between seasons.

## Five-minute collection cadence

**Every TopDeck request shares one budget:** at least 10.05 seconds between calls and at most six calls per rolling 60.05 seconds. Discovery, event metadata, round reads, and retries all count. `429` and transient server errors use bounded backoff/`Retry-After`; no attempt bypasses the shared gate. API failures retain last-good records and become public source warnings.

Scheduled runs are finite: at most one round read per configured ongoing event, with daily completed-deck discovery and a 15-minute metadata interval. Unchanged runs skip Pages deployment. The manual `force` option refreshes completed decks before their daily interval. The optional manual `live_minutes` input accepts 0 (off) or 1–60 and samples ongoing events in rotation during that bounded period; it is unnecessary for the normal five-minute schedule. Only public table names, players' public display names, results, and status are retained. No attendee contacts, account metadata, full profiles, win-rate matrix, or derived tier list is retained.

**GitHub Pages publishes only after the run finishes.** The five-minute cron is the lowest supported schedule, not an uptime/freshness guarantee: jobs may be delayed or dropped, and collection/deployment takes additional time. Repeated deploys every ten seconds are unsupported. The Android app reads cached data immediately, checks decks daily, and checks every five minutes only while Events is visible after opt-in. Manual refresh is also available. Records distinguish content update time (`updated_at`) from actual source fetch time (`fetched_at`).

No separate relay is needed for the agreed five-minute snapshots. Users can open the original event page for live coverage. App clients never contact TopDeck, so their number does not multiply authenticated API requests.

## Format and trust boundary

Schema version is `1`. Manifest fields are `generated_at`, `sources`, `packs`, `source_state`, `warnings`, and a configuration fingerprint. State carries source fetch times and the last six request times so the budget persists between successive serial jobs.

Each pack has `schema_version`, `generated_at`, `sources`, `decks`, and `events`. Every entry references a declared source. All source/coverage URLs are HTTPS. Canonical IDs retain the source namespace (`topdeck:TID` and `topdeck:TID:playerID`); no numeric event IDs are treated as globally unique. Code/text import is validated against the app catalog and unknown cards need an explicit incomplete-copy choice.

Pack descriptors include a relative path, exact byte size and SHA-256 hash. The app accepts 2 MB per pack and a 20 MB total cache budget. It defaults to the events pack; deck batches require selection. Sources, generation times and record update times travel with the file for offline attribution. Personal deck copies are separate records and are never overwritten by later pack updates.

The previous published manifest/packs are recovered only from the configured GitHub Pages origin, without redirects, with byte/hash limits. A failure recovering an existing feed stops publication. Source API failure keeps the old records; it never invents a successful update. The feed holds at most 1,000 decks and 1,000 events. No raw authenticated responses or keys are written to disk/artifacts. Public response parsing accepts only explicitly supported section/count shapes; unknown shapes remain original-source links.

Additional selections contain decks for an individual legend and records for specific recent
events. Existing bulk pack IDs remain compatible. These selections use the same verified
source records; they do not turn source-only references into full lists. The publisher caps
the manifest at 140 packs, each file at 2 MB and the combined output at 20 MB.

## Maintenance and removal

- Review source permissions/retention terms and [Riot's Riftbound developer policy](https://developer.riotgames.com/policies/riftbound) for this exact app. The app is registered and awaiting review as of 5 October 2026. No Riot API is called by this pipeline. A Riot key alone does not provide tournament decklists or authorize a new public integration.
- Do not add aggregate deck/card play rates, win rates, matchup percentage matrices or inferred skill rankings. The dedicated Riftbound policy prohibits publishing or retaining metagame-defining data. Keep tournament decklist browsing and existing private match summaries in the app's review scope rather than assuming an exception. Do not add undocumented UVS/Zero endpoints or crawl deck sites. Additional full lists require an authorized export/feed and applicable Riot review.
- GitHub Pages is static hosting with [size/bandwidth limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits). Keep images out of packs, and watch aggregate downloads before promising unlimited scale.
- An invalid/expired key or provider shape change appears in the manifest warnings. The app keeps last-good cache and original source links.
- Record IDs can be excluded via `exclude_deck_ids`/`exclude_event_ids` in config when a source author requests removal. These exclusions apply before publishing. Old downloaded snapshots can remain offline until refreshed/cleared; imported personal copies/notes are separate user records. Agree on provider removal/retention behavior before promising permanent archival.
- To stop publishing, disable the workflow in GitHub Actions. Users can independently turn off updates or clear community downloads without affecting their collection, saved personal decks, bookmarks or notes.

No external libraries are required. Seven local fixture checks cover schema/hashes/attribution, legend/event packs, strict export shapes, contact-field omission, distinct fetched/update times, request/retry budget, and last-good recovery. Run them with `python -m unittest discover -s community_pipeline -p test_feed.py`; the workflow runs the same small checks before collection. These tests make no network calls and use no real credentials. No Android build is performed here.

## First published corpus

The first successful 90-day collection on 5 October 2026 returned 112 real completed events and 1,000 retained deck references (the configured cap). Inspection of the published packs found **zero importable text lists and zero deck codes**; all references link to the original TopDeck event and retain the publicly provided leader/byline. The app displays source links and does not invent missing card contents. Import preview/save is available for authorized future exports and user-imported pack files, not for these source-only references. No ongoing event IDs are configured yet, so current public results are empty until a real TopDeck event is explicitly tracked.
