# Riftbound community snapshots

Optional, free offline packs for the Android app. This repository uses the documented [TopDeck public API](https://topdeck.gg/docs/tournaments-v2), with visible attribution. It does not scrape other deck websites, mirror card artwork, upload personal collection data, or read staff-only/contact endpoints.

## Install in `nowaddlearound/riftbound-decksapi`

| Local file | Repository destination |
| --- | --- |
| `community_pipeline/build_feed.py` | `community_pipeline/build_feed.py` |
| `community_pipeline/sources.json` | `community_pipeline/sources.json` |
| `community_pipeline/community.yml` | `.github/workflows/community.yml` |
| `community_pipeline/README.md` | `README.md` |

1. Keep the repository public if using free public GitHub Actions runners and free Pages.
2. Set **Settings → Pages → Source → GitHub Actions**.
3. Set the repository Actions secret `TOPDECK_API_KEY` to the developer key. Never put it in source, URLs, the Android app, or JSON packs. The supplied workflow passes it only as a runner environment variable.
4. Run **Daily community snapshot** manually once. The normal schedule is 04:17 UTC daily. Schedule timing is inexact, and inactive public repository schedules can be disabled after 60 days. See [GitHub schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
5. The manifest becomes `https://nowaddlearound.github.io/riftbound-decksapi/community/manifest.json`. Prices remain in the independent `riftbound-prices` repository and are unaffected.

The first successful run may contain only source links if a public deck's export is a website URL. This is an honest availability limit: public access to a linked website is not permission to crawl it. No sample or fabricated deck/event data is published.

## Configure sources

`sources.json` starts with completed Riftbound Constructed events from the last 14 days. Supported TopDeck formats are `Constructed`, `Limited`, `Sealed`, `2v2`, and `Free-for-All`. A request is made per selected format. The lookback can be 1–90 days.

`topdeck.tracked_tournaments` accepts up to 20 **real TopDeck tournament IDs**. Their public metadata is fetched separately. Upcoming events cannot be discovered by the completed-event search. Get IDs from an actual TopDeck event URL; a Zero/UVS event ID is not necessarily a TopDeck ID.

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

## Collection cadence and the 10-second limit

**Every TopDeck request shares one budget:** at least 10.05 seconds between calls and at most six calls per rolling 60.05 seconds. Discovery, event metadata, round reads, and retries all count. `429` and transient server errors use bounded backoff/`Retry-After`; no attempt bypasses the shared gate. API failures retain last-good records and become public source warnings.

The manual `live_minutes` input accepts 0 (off) or 1–60. For configured ongoing Riftbound events, it collects `/rounds/latest` in rotation during that bounded period. Six calls per minute across three events means each event is sampled about every 30 seconds. Only public table names, players' public display names, results, and status are retained. No attendee contacts, account metadata, full profiles, win-rate matrix, or derived tier list is retained.

**GitHub Pages publishes only after the run finishes.** A ten-second source polling loop does not make Pages a ten-second live relay. Actions scheduling has a five-minute minimum and may be delayed or dropped. Repeated deploys every ten seconds are unsupported. The Android app uses daily/manual cached reads and labels results as snapshots.

To expose shared ten-second updates, a separate continuously running HTTPS service is necessary. It should hold the key, run one shared collector, return only sanitized cached data, and gate all requests through the same budget. Client refreshes must never fan out to TopDeck. No such service is deployed or secretly assumed here; its hosting, provider retention rules, TLS, uptime, and operating costs require a concrete host choice. Until then, users can open the source event page for live coverage.

## Format and trust boundary

Schema version is `1`. Manifest fields are `generated_at`, `sources`, `packs`, `source_state`, and `warnings`.

Each pack has `schema_version`, `generated_at`, `sources`, `decks`, and `events`. Every entry references a declared source. All source/coverage URLs are HTTPS. Canonical IDs retain the source namespace (`topdeck:TID` and `topdeck:TID:playerID`); no numeric event IDs are treated as globally unique. Code/text import is validated against the app catalog and unknown cards need an explicit incomplete-copy choice.

Pack descriptors include a relative path, exact byte size and SHA-256 hash. The app accepts 2 MB per pack and a 20 MB total cache budget. It defaults to the events pack; deck batches require selection. Sources, generation times and record update times travel with the file for offline attribution. Personal deck copies are separate records and are never overwritten by later pack updates.

The previous published manifest/packs are recovered only from the configured GitHub Pages origin, without redirects, with byte/hash limits. A failure recovering an existing feed stops publication. Source API failure keeps the old records; it never invents a successful update. The feed holds at most 1,000 decks and 1,000 events. No raw authenticated responses or keys are written to disk/artifacts. Public response parsing accepts only explicitly supported section/count shapes; unknown shapes remain original-source links.

## Maintenance and removal

- Review source permissions/retention terms and [Riot's Riftbound developer policy](https://developer.riotgames.com/docs/riftbound) for this exact app. API integration permission should not be extrapolated to unrelated website content or public meta analytics.
- GitHub Pages is static hosting with [size/bandwidth limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits). Keep images out of packs, and watch aggregate downloads before promising unlimited scale.
- An invalid/expired key or provider shape change appears in the manifest warnings. The app keeps last-good cache and original source links.
- Record IDs can be excluded via `exclude_deck_ids`/`exclude_event_ids` in config when a source author requests removal. These exclusions apply before publishing. Old downloaded snapshots can remain offline until refreshed/cleared; imported personal copies/notes are separate user records. Agree on provider removal/retention behavior before promising permanent archival.
- To stop publishing, disable the workflow in GitHub Actions. Users can independently turn off updates or clear community downloads without affecting their collection, saved personal decks, bookmarks or notes.

No external libraries are required. No test/build commands are run by the deployment workflow; it validates source/output while collecting and publishing the authorized data.
