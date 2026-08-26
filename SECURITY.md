# Security Policy

## Supported versions

| Version | Supported          |
|---------|--------------------|
| 0.x (latest on `main`) | :white_check_mark: |
| older commits          | :x:                |

janusline is pre-1.0. Only the latest state of the default branch receives fixes.

## Reporting a vulnerability

Please report security issues **privately** through
[GitHub Security Advisories](https://github.com/oh-namgyu/janusline/security/advisories/new)
on this repository. Do not open a public issue for a sensitive report. You can
expect an initial response within a few days.

## Threat model

janusline is a **single-user, self-hosted** tool. It binds `127.0.0.1` by
default, holds no user accounts, and treats the machine it runs on as trusted.
The interesting boundaries are the network exposure of the HTTP port, the
untrusted text that arrives in a news feed, and the untrusted text that comes
back from an LLM.

## Built-in hardening

- **Bind guard.** Binding a non-loopback address without `AUTH_TOKEN` is a hard
  startup failure (`SystemExit(1)`), not a warning. Misconfigured exposure is
  therefore impossible to do silently.
- **Token authentication.** With `AUTH_TOKEN` set, a login form takes the token,
  compares it with `hmac.compare_digest` (constant time), and issues a session
  cookie whose value is `HMAC-SHA256(AUTH_TOKEN, timestamp)`. The cookie is
  `httpOnly`, `SameSite=Strict`, `Secure` when the request is HTTPS, and expires
  after 8 hours. Without a token the app is in open mode — intended only for a
  loopback bind.
- **Same-origin gate.** `POST` / `PATCH` / `PUT` / `DELETE` additionally require an
  `Origin` or `Referer` whose host:port matches the request host. Combined with
  `SameSite=Strict` this covers CSRF and DNS rebinding.
- **Content-Security-Policy.** Every response carries
  `default-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'`,
  plus `X-Content-Type-Options: nosniff` and `Referrer-Policy: same-origin`.
- **Slug guard.** Brief slugs must match `^[a-z0-9-]{1,64}$`, and the resolved path
  is re-checked to be a direct child of `data/briefs/` before any read or write.
  Path traversal is rejected with `400`.
- **No SSRF: fixed-host fetching.** The only host the server contacts is
  `news.google.com`. The user's query is URL-encoded into the RSS query string and
  can never influence the scheme, host or path, so no user input reaches a URL the
  server will open. **Article links are never fetched** — they are stored and
  rendered as links only, which is why a hostile feed entry cannot make the server
  request an internal address.
- **Link scheme validation.** An article whose link is not `http`/`https` is
  dropped at collection time — a `javascript:` or `data:` URL never enters
  storage. The export re-validates the scheme at render time rather than trusting
  the stored brief, and every outbound link carries
  `rel="noopener noreferrer" target="_blank"`.
- **Prompt-injection boundary.** RSS titles and snippets are untrusted third-party
  text. They are wrapped in an explicit `<articles>` data block; the angle
  brackets in article text are replaced with look-alike characters so a crafted
  headline cannot close its own block or forge a new one; and both system prompts
  state that everything inside the block is data to be classified, never an
  instruction to follow. A fixture test feeds an injection attempt through the
  pipeline.
- **Model output is never trusted.** Replies are parsed as strict JSON against a
  fixed shape. Ids that were not sent are discarded, ids the model skipped fall
  back to `neutral`, a sentiment outside the enum is not a judgement, an
  `evidence` quote that is not a verbatim substring of its own article is demoted
  to `null`, and `citations` are filtered to ids that actually exist. The
  disclosure caveat is written by the server, not the model, so a reply cannot
  soften, rewrite or drop it.
- **Stored-XSS defence.** Feed- and model-derived strings are injected into the UI
  with `textContent` only — `innerHTML` is not used for such data. The export
  document escapes every string server-side with `html.escape`.
- **Secret handling.** The API key is read from the server environment only. It is
  never persisted, echoed in a response, or logged.
- **No upload, no user-supplied fetch.** The app accepts no file uploads and opens
  no URL a user chose.
- **Atomic writes.** `brief.json` is written to a temp file and `os.replace`d, with
  the previous good copy rotated to `brief.json.bak`; analysis runs entirely in
  memory and lands in one write, so a failed provider call leaves the file byte
  for byte unchanged. If both the file and its backup are unreadable, the damaged
  bytes are preserved as `brief.json.corrupt-<ts>` and the caller is told data was
  lost — a brief is never silently emptied. Deletes are an atomic `os.rename` into
  `data/.trash/`.

## Plaintext transport — read before exposing

**janusline does not terminate TLS.** Traffic, including the token you type into
the login form, is plain HTTP. A non-loopback bind prints a warning saying so.

If you expose it beyond loopback, putting it behind a **TLS-terminating reverse
proxy** (nginx, Caddy, Traefik) is a requirement, not a suggestion. The
`SameSite=Strict` cookie is also only marked `Secure` when the request arrives
over HTTPS, which requires that proxy.

## Known limitations

- **No rate limiting.** Nothing throttles login attempts, collection or analysis.
  A leaked token is both an access problem and a spending problem. Rate limit at
  the reverse proxy if the instance is reachable by anyone else.
- **One shared token.** There are no accounts and no per-user separation; everyone
  who has `AUTH_TOKEN` has full access to every brief.
- **Single process.** Storage safety relies on in-process locks, so running
  multiple workers is unsupported and unsafe.
- **Trusted local machine.** `data/` is stored unencrypted, readable by anything
  running as the same user. Search queries are part of that data.
- **Upstream feed trust.** Article metadata is whatever Google News returns.
  janusline validates and escapes it, but it cannot verify that a headline or a
  source attribution is genuine.

## Not a security boundary

The analysis output is **not** a safety or accuracy control. Sentiment labels,
summaries and scenarios are machine generated from headlines alone and can be
wrong; see the disclaimer in [README.md](README.md). Treating a janusline brief
as a verified finding about a person or an organisation is a misuse of the tool,
not a vulnerability in it.
