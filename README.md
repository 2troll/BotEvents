# 🛰 Kansai Radar

An **autonomous, 100% free** daily event bot for the Kansai region (Osaka,
Kyoto, Kobe, Nara, Hyogo, Wakayama, Shiga). After a one-time setup it runs by
itself every day on **GitHub Actions** and pushes event notifications to
**Telegram** — no servers, no database, no paid APIs.

- Collects upcoming public events from free, keyless sources (Connpass, iCal,
  RSS, public HTML pages, optional DuckDuckGo discovery).
- Normalizes, geocodes (OpenStreetMap **Nominatim**, cached), and de-duplicates.
- Scores each event against **your interests** with local bilingual (EN/JP)
  keyword rules — **no LLM, no AI API calls**.
- Sends a **morning digest** + **smart reminders** (30 / 7 / 1-day heads-up for
  major events, day-before for normal ones, and "starting soon" intraday).
- Regenerates a public **Leaflet + OpenStreetMap** map (`docs/index.html`).
- Auto-cleans past events so state stays small, and commits state back to the
  repo (which also keeps the cron alive).

> 💴 **Cost: zero.** The only secret you provide is a free Telegram bot token
> and chat id. No credit card, no billing account, anywhere.

---

## 🔧 6-step setup

### 1. Create a Telegram bot and copy the token
In Telegram, message [@BotFather](https://t.me/BotFather), send `/newbot`,
follow the prompts, and copy the **HTTP API token** it gives you
(`123456:ABC-...`).

### 2. Get your chat id
Message your new bot once (say "hi"), then open:
```
https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
```
Find `"chat":{"id":...}` in the JSON — that number is your **chat id**.
(Tip: for a group, add the bot to the group and read the group's negative id.)

### 3. Create / fork this repo
Fork it to your own GitHub account (or push this code to a new repo of yours).

### 4. Add the two Action secrets
In your repo: **Settings → Secrets and variables → Actions → New repository
secret**. Add:
- `TELEGRAM_BOT_TOKEN` — the token from step 1
- `TELEGRAM_CHAT_ID` — the id from step 2

### 5. Enable GitHub Pages for the map
**Settings → Pages →** Source: *Deploy from a branch*, Branch: your default
branch, Folder: **`/docs`**. Save. Your map will live at
`https://<you>.github.io/<repo>/`. Put that URL in `config.yaml` under
`telegram.map_public_url`.

### 6. Enable Actions — done
**Actions** tab → enable workflows. The bot now runs itself on the schedule in
`.github/workflows/radar.yml`. Trigger the first run manually with **Run
workflow** (workflow_dispatch) to confirm it works.

That's it — it's autonomous from here. 🎉

---

## 🧪 Local test mode

```bash
pip install -r requirements.txt

# Print what it WOULD send/do — no Telegram I/O, no state changes sent:
python -m radar --once --dry-run

# Force the digest immediately (ignores the once-per-day / hour gate):
python -m radar --force-digest --dry-run

# Run the offline test suite:
python -m unittest discover -s tests
```

CLI flags: `--once`, `--dry-run`, `--force-digest`, `--skip-collect`,
`--verbose`, `--config PATH`, `--state PATH`.

---

## ✏️ Editing your interests and sources

Everything tunable lives in **`config.yaml`** — no code changes needed.

- **Interests**: each entry has a `tag`, `weight`, `emoji`, and bilingual
  `keywords`. An event's score is the sum of matched interest weights; it is
  kept when the score ≥ `score_threshold`. Raise a weight to prioritise a
  topic; lower the threshold to be less picky.
- **Major events** (get advance reminders): any event whose category is in
  `major_categories`, or whose `attendee_count ≥ major_attendee_threshold`.
- **Reminders**: tune `major_days`, `normal_day_before`, `intraday_hours`.
- **Sources**: enable/disable each, and add URLs/queries:
  - `connpass` — keyless JSON API (tech/meetup/language). If Connpass later
    requires a key, add an optional `CONNPASS_API_KEY` secret; it stays
    optional and the run never breaks without it.
  - `ical.feeds` — list of public `.ics` calendar URLs.
  - `rss.feeds` — list of public RSS/Atom feed URLs.
  - `html.pages` — public listing pages parsed by CSS selectors (data-driven;
    one entry per site). Respect each site's robots.txt and ToS.
  - `duckduckgo` — optional, off by default; best-effort discovery leads.

Add your own real feed URLs to `ical`/`rss`/`html` to enrich coverage — the
shipped config includes the structure and commented examples.

### Source status (out of the box)

| Source | Works on day one? | Notes |
|---|---|---|
| **WelcomeJapan / Wix Events** (`welcometokyoevents.com/osaka`) | ✅ enabled & verified | Free, public, **no key/account**. Real **dated + geolocated** events: Kansai international meetups, language exchange, parties — strong overlap with your interests. Parsed from the page's embedded structured JSON (not fragile HTML scraping); that site's robots.txt allows it. Add more public Wix event pages under `sources.wixevents.pages`. |
| **Time Out Osaka / Kyoto RSS** | ✅ enabled & verified | Free, public, English. Brings real Kansai event/news leads immediately. RSS items carry a *publish* date (not the event date), so they act as near-term leads filtered by your keywords; past items auto-purge and only fresh ones surface in each day's digest. |
| **Connpass** | ⚠️ needs a free key | Best structured source for tech / language-exchange / meetup / hiking / halal community events. As of 2026 the API requires a **free** key (see below). Without it, this source skips itself silently. |
| **iCal / HTML** | scaffolded | Empty by default — add public `.ics` calendars or listing pages you trust. Many big tourism sites load events via JavaScript or block bots, so they can't be scraped with `requests`; prefer official `.ics` feeds. |
| **DuckDuckGo discovery** | off | Optional, best-effort, low-confidence leads. |

### Getting the free Connpass key

1. Email Connpass support (see their API page / developer docs) to request an
   API key for personal/community use — it's **free**, replies usually arrive
   within about a week.
2. Add it as a repository secret named `CONNPASS_API_KEY` (Settings → Secrets →
   Actions). The workflow already passes it through.
3. That's it — Connpass events start flowing on the next run. If you never add
   it, everything else keeps working.

> 💡 Want precise dates, venues and map pins? Add **iCal (`.ics`)** feeds — they
> carry structured start/end times and locations, unlike RSS article feeds.

---

## 🤖 Optional chat commands

If `telegram.commands_enabled` is on, each scheduled run polls `getUpdates` and
answers commands **and button taps** (no server needed):

**Tappable buttons** (no typing required):
- A persistent **bottom keyboard** with: 📅 Hoy · 🗓 Semana · 🗺 Mapa · ⭐ Grandes ·
  📋 Menú · 🆘 Ayuda · and quick interest filters (🕌 Halal, 🥾 Senderismo,
  🐎 Caballos, 🗣️ Idiomas, 🎆 Fuegos, 🎉 Fiesta).
- `/menu` opens an **inline menu** with a button per interest.
- Every event card has **🙋 Voy** (mark you're going) · **🗺 Mapa** · **🔗 Info**.
- Telegram's **`/` menu** is registered (`setMyCommands`) for autocomplete.

| Command | Does |
|---|---|
| `/hoy` | Events happening today |
| `/semana` | Events in the next 7 days |
| `/major` | Big/"major" events only |
| `/<tag>` | Events matching an interest tag, e.g. `/halal`, `/tech`, `/fireworks` |
| `/mapa` | Link to the live map |
| `/menu` | Button menu |
| `/voy <event_id>` | Mark "I'm going"; shown on the map's personal layer |
| `/ayuda` | Help |

Replies arrive on the **next scheduled run** (the workflow runs every ~2 hours),
so they are not instant — this is the trade-off for being 100% serverless and
free. URL buttons (🗺 Mapa, 🔗 Info) open instantly; action buttons (🙋 Voy,
filters) are processed on the next run.

### ⚡ Want INSTANT replies? Deploy `--serve` on a free 24/7 host

The same code can run as a long-lived process that answers commands and button
taps **immediately**, while still doing the autonomous digest/reminders/map on
an interval. It's free and needs no credit card on Telegram-bot hosts such as
**[Pella](https://www.pella.app/free-telegram-bot-hosting)** or
**[JustRunMy.App](https://justrunmy.app/telegram-bots)**.

1. On the host, deploy this GitHub repo.
2. Set the **start/run command** to:
   ```
   python -m radar --serve
   ```
   (it installs `requirements.txt` automatically on most hosts).
3. Set environment variables:
   - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (required)
   - *Optional, recommended* — so the public map keeps updating and state
     survives restarts: `GITHUB_TOKEN` (a fine-grained token with **Contents:
     read & write** on this repo), `GITHUB_REPO=2troll/BotEvents`,
     `GITHUB_BRANCH=<your default branch>`.
4. **Important:** disable the **GitHub Actions** "Kansai Radar" workflow while
   `--serve` is running. Telegram allows only one `getUpdates` consumer, so the
   two would otherwise fight over updates. In `--serve` mode the process does
   everything the Action did (digest, reminders, map) plus instant replies.

Local test: `python -m radar --serve --serve-interval 600` (runs the pipeline
every 10 min and answers instantly in between). Stop with Ctrl-C.

> Trade-off: `--serve` needs a host that stays awake. The free Telegram-bot
> hosts above don't sleep. If you ever stop the host, just re-enable the GitHub
> Actions workflow and you're back to the (slower but zero-host) mode.

---

## ⏱ Scheduling notes (free tier)

- Cron times in the workflow are **UTC** and are **not minute-exact** on the
  free tier — the queue can delay a run by several minutes. That's fine: the
  digest is gated to once per day at/after `telegram.digest_hour` (JST), and
  reminders are idempotent.
- GitHub disables schedules after **60 days of repo inactivity**. The workflow
  commits updated `state.json`/`docs/` every run, which keeps the repo active
  and the cron alive.
- Everything is **idempotent**: per-event, per-tier "already notified" flags in
  `state.json` mean a reminder is never sent twice, no matter how often it runs.

---

## 🗂 Project layout

```
radar/
  __main__.py        CLI entrypoint (python -m radar)
  pipeline.py        orchestrates one full run
  config.py          config.yaml + env-secret loading
  models.py          the normalized Event data model
  state.py           state.json persistence (events, cache, going, offsets)
  scoring.py         local keyword/rule-based relevance scoring
  geocode.py         cached, rate-limited Nominatim geocoding
  dedupe.py          cross-source de-duplication
  reminders.py       reminder-tier decision logic
  messages.py        Telegram message formatting (HTML)
  telegram.py        Bot API client (send + getUpdates, 4096-char splitting)
  commands.py        optional /hoy /semana /<tag> /mapa /voy handling
  map_generator.py   writes docs/index.html (Leaflet + OSM)
  sources/           pluggable collectors: connpass, ical, rss, html, duckduckgo
config.yaml          interests, sources, thresholds, reminders, map, telegram
state.json           persisted state (committed back by the Action)
docs/index.html      the generated public map
.github/workflows/radar.yml   the scheduled, free GitHub Actions job
tests/               offline unit tests
```

---

## 🔒 Privacy & etiquette

- Collects only **public** data via official free APIs / RSS / iCal / public
  HTML. Does **not** scrape Facebook/Instagram and creates no accounts.
- Sends a descriptive `User-Agent`, respects Nominatim's ≤1 req/sec policy, and
  caches geocoding results permanently to minimise requests.
- Keep your bot token secret — it lives only in GitHub Actions secrets, never
  in the code or config. If it ever leaks, revoke it in @BotFather (`/revoke`)
  and update the secret.
