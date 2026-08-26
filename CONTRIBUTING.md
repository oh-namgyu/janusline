# Contributing to janusline

Thanks for your interest! janusline is a small, dependency-light project and
contributions are welcome.

## Development setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
playwright install chromium         # once, for the browser tests

python -m pytest -q                 # unit suite (no network, no API key)
python -m pytest e2e -q             # browser round trips against a real server

JANUSLINE_FAKE=1 python app.py      # run the UI offline at http://127.0.0.1:6181
python scripts/preflight.py         # check the live RSS endpoint before debugging collection
```

`JANUSLINE_FAKE=1` swaps in fixture feeds and an offline analyst, so you can
develop the whole app without a key, a network or any spending. The e2e suite
skips itself rather than failing when chromium is not installed.

## Conventions

- **Keep files small.** A source file over ~300 lines, or a function over ~50,
  wants splitting.
- **No inline styles.** Every style is a reusable class in the global
  `static/style.css` — no `style="..."` attributes, no per-component stylesheets.
- **`textContent` only** for feed- and model-derived strings. `innerHTML` with
  such data is a stored-XSS bug, and the tests check for it.
- **The unit suite never touches the network.** Collector tests run the real
  parsing pipeline over saved feeds in `tests/fixtures/` with `fetch()` stubbed;
  analyst tests use scripted stubs. A test that would open a socket does not
  belong in `tests/`.
- **Never trust a model reply.** New fields must be validated, bounded and
  reconciled against what was sent, the way `core/analyze.py` already does.
  Disclosure text is written by the server, never by the model.
- **Keep dependencies minimal.** Flask, feedparser and the Anthropic SDK, which is
  imported lazily so the tests never need it.
- **Collection stays behind the adapter.** New sources implement the same
  `collect(query, period_days, langs)` shape as `core/collect.py` and ship with
  saved feed fixtures.
- **Type hints** on new functions.
- **Add or update tests** in `tests/` (or `e2e/`) for every behaviour change.

## The UI is English

All interface strings, including status and error text, are English. Korean
belongs in `README_KOR.md` and in test fixtures that stand in for Korean-edition
articles — not in the app.

## Pull requests

Keep PRs focused on one change. Describe what changed and how you verified it,
and make sure `python -m pytest -q` is green before opening one. CI runs the unit
suite on Python 3.10 and 3.12, the e2e suite on 3.12, and a Docker build smoke
test.
