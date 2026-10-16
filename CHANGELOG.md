# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-10-16

### Changed

- The Docker image is built on `python:3.14-slim` (was `3.12-slim`).
- Minimum dependency versions raised: `flask>=3.1.3`, `feedparser>=6.0.14`,
  `anthropic>=1.13.0`; for development, `pytest>=9.1.1` and
  `pytest-playwright>=0.10.0`.

## [0.1.0] - 2026-08-26

Initial public release.

### Added

- A self-hosted Flask app that turns one search query into a dual-sided news
  brief: favourable coverage on the left of a vertical timeline, unfavourable
  on the right and neutral items on the centre rail, with two opposing
  readings and an "IF this reading is right" scenario for each.
- Collection from the public Google News RSS feed with no API key: Korean and
  English editions, deduplicated and period filtered (30, 90 or 365 days), up
  to 40 articles per brief (20 per edition).
- Analysis through the Anthropic API (`ANTHROPIC_API_KEY`, optional):
  sentiment relative to the searched subject, a one-line summary and an
  evidence quote per article in batches of 25, plus one synthesis call.
  Replies are schema-validated and retried once; evidence quotes must be
  verbatim substrings of the article's title or snippet, and citations must
  be ids of articles that were sent. Without a key, collecting, browsing and
  exporting still work.
- Export of a brief as one standalone HTML file with the stylesheet inlined,
  no scripts and no external references.
- Plain-file storage under `data/briefs/<slug>/brief.json`, with deleted
  briefs moved to a trash folder and purged after 7 days.
- Security defaults: loopback bind, a hard startup failure for a
  non-loopback bind without `AUTH_TOKEN`, token login with an HMAC-signed
  session cookie, an `Origin`/`Referer` gate on writes, feed text treated as
  untrusted data in prompts and rendered with `textContent` only.
- `JANUSLINE_FAKE=1` for fully offline use with fixture feeds and an offline
  analyst.
- Dockerfile and `compose.yml`, plus `scripts/preflight.py` to check the live
  RSS endpoint.
