# Jev via OpenRouter

The bot uses OpenRouter's typed Decisions API, not chat completions:
`POST https://openrouter.ai/api/alpha/decisions`, model `typesafe/jev-1.13`.
The implementation follows the supplied Jev tutorial. It has been verified
offline with mock responses; live endpoint compatibility and gameplay performance
have not been verified in this environment.

## Local OCR on macOS

`LOCAL_OCR_BACKEND = "auto"` (also the default when absent) uses Apple's native
Vision text recognition on macOS and EasyOCR on other platforms. Set
`"easyocr"` to retain EasyOCR on a Mac, or `"apple_vision"` to request Vision
explicitly on macOS. Other platforms continue to use EasyOCR.

Vision is accessed through the existing macOS PyObjC dependency; no `ocrmac`,
MLX model or paid OCR service is required. Recognition runs locally using
lossless PNG bytes in memory, accurate English recognition and language
correction disabled. The text-list interface is unchanged; native confidence
values are not substituted for the existing observation-quality indicators.

If Vision fails or its bindings are missing, the bot logs only the exception
type and uses local EasyOCR for 600 seconds before trying Vision again. Empty
recognition remains an empty result. Keep `GROQ_API_KEY = ""` for local-only OCR;
a configured Groq key still opts into the existing cloud-first OCR behavior.

`tests/test_local_ocr.py` checks routing, fallback/cooldown, interruption, image
encoding and native request configuration. A macOS-only test recognizes a
rendered number using the actual framework. On other systems this test is
skipped; mock tests do not establish accuracy on real Clash screenshots.

## Enable upgrade decisions

Keep the OpenRouter key in the environment of the process that starts the bot:

```sh
export OPENROUTER_API_KEY='your-key'
python src/main.py
```

Add these settings to your existing `src/configs.py` (setup does not overwrite
that file), or use the documented defaults in `src/configs.template.py`:

```python
JEV_MODE = "shadow"
JEV_OBJECTIVE = "farm_and_upgrade"  # or "trophies"
JEV_UPGRADES = True
JEV_BASE_SELECTION = False
JEV_DEPLOYMENT = False
```

`off` uses the original choices and makes no API calls. `shadow` evaluates the
recognized alternatives but returns the original choice; it adds no menu clicks,
scrolls, base skips or alternate deployments. `active` can apply accepted choices.
New installations default to `shadow`, BlueStacks instance `BlueStacks Air`,
upgrade advice enabled and automatic local OCR. Setup preserves an existing
`src/configs.py`; change these settings there manually when updating an install.
Missing settings in older configs default to `off`. Missing keys, API errors,
invalid responses, low confidence, low observation quality and stale snapshots
retain the original choices. No automatic API retries are made.

Jev chooses among recognized candidates on the current menu page. Existing
priority-level iteration, discount preference, affordability, hero exclusions,
builder reservations and lab availability remain in force. In active mode, the
selected row's name/affordability are checked on a fresh frame, including when
Jev keeps the original choice after an API wait. The confirmation
dialog must show the selected name next to the existing upgrade-title anchor,
and exclusions are checked again. Name and button recognition are retried through
screen transitions within the existing confirmation timeout. An
unreadable or changed confirmation is abandoned rather than clicked. Costs,
levels and upgrade durations not read by the bot are sent as unknown information,
not invented. Choices across the entire village or a whole scrolled upgrade list
are not claimed.

`Choice.confidence` measures distribution concentration. The chosen option's
`probabilities[choice]` is a different field. Both gates must pass, initially
`JEV_MIN_CONFIDENCE = .70` and `JEV_MIN_PROBABILITY = .80`. These are starting
values for calibration, not claims of accuracy. Noul and Score responses are
also supported and validated by the client; the game policies currently use Choice.
Questions in a single request are independent. Game decisions that depend on
earlier answers are made sequentially.

## Limits and costs

Defaults: 1 second connection timeout, 2 seconds read timeout, a 3 second total
API deadline, a 128 KB response limit, 60 seconds
cooldown after failures, 1000 requests and $1 accounted usage per bot process.
The attacker and upgrader share one client/budget. Separate emulator processes
have separate budgets; limits reset on restart. Configure the OpenRouter key's
own spending limit if you need an account-level hard cap.

Each dispatched request reserves `JEV_RESERVE_COST_USD` ($0.01 initially).
The actual `usage.cost` replaces that reservation, even if answers are invalid.
Timeouts and malformed/missing usage retain it because the charge is unknown.
The next call is blocked if its reservation would exceed `JEV_MAX_COST_USD`.
This is local accounting, not a guaranteed cap on the current request's charge.
The total deadline returns control to the bot even if a peer keeps sending bytes.
One daemon transport worker may finish after that deadline; until it finishes,
new requests are blocked. Its late response cannot change decisions or accounting.
No token price or current model availability is assumed. Keys, HTTP headers,
response bodies and exception messages are not written to telemetry.

## Attack recognition: real screenshots required

The repository does not contain calibrated loot/Next-button screenshots or a
deployment-terrain dataset. Attack features are implemented but disabled by
default. They require both their feature switch and a validated local profile:

```python
JEV_BASE_SELECTION = True
JEV_DEPLOYMENT = True
JEV_SCREEN_PROFILE_PATH = "/absolute/path/to/profile.json"
```

Create the profile using actual RGB screenshots at the bot's configured
resolution (normally 1920×1080). The file paths below are relative to the
profile file. Regions are normalized `[left, top, right, bottom]` coordinates:

```json
{
  "version": 1,
  "validated": false,
  "resolution": [1920, 1080],
  "templates": {
    "scouting": {"path": "scouting-label.png", "region": [0.2, 0.0, 0.8, 0.15], "threshold": 0.95},
    "next": {"path": "next-button.png", "region": [0.8, 0.5, 1.0, 0.82], "threshold": 0.95}
  },
  "loot_regions": {
    "gold": [0.0, 0.1, 0.2, 0.15],
    "elixir": [0.0, 0.15, 0.2, 0.2],
    "dark_elixir": [0.0, 0.2, 0.2, 0.25],
    "search_cost": [0.85, 0.68, 0.98, 0.74]
  },
  "base_region": [0.2, 0.2, 0.8, 0.7],
  "deployment": {
    "home": {
      "anchor": {"path": "home-camera-anchor.png", "region": [0.05, 0.1, 0.3, 0.3]},
      "playable_mask": "home-playable-mask.png"
    },
    "builder": {
      "anchor": {"path": "builder-camera-anchor.png", "region": [0.05, 0.1, 0.3, 0.3]},
      "playable_mask": "builder-playable-mask.png"
    }
  }
}
```

**The coordinates above illustrate the schema; they are not calibrated game
coordinates.** Replace every region and screenshot asset using your own frames.
Crop nonconstant, distinctive scouting and Next-button templates. Loot regions
must contain only digits; grouped numbers are accepted, ambiguous OCR such as
`12.5K`, `1O00` or a label is rejected. Gold, elixir and the search cost are
required; missing dark elixir stays `null`. Exclude countdowns, UI and moving
decorations from `base_region`, which identifies the current base after a skip.

For deployment, capture frames after the bot's existing zoom-out and swipe-up.
Provide a grayscale mask at the exact full-frame resolution: white marks
deployable terrain, black excludes UI, off-map terrain and obstacles. The camera
anchor must identify the map/camera alignment, not merely a static UI control.
The detector additionally requires one substantial closed red base boundary;
it fills and expands the forbidden footprint and erodes the terrain mask before
offering any point. Missing, fragmented or ambiguous boundaries use the legacy
position. Validate against representative bases, scenery, camera changes and
both villages before setting `validated` to `true`. That flag records your local
calibration; it is not a model confidence score or an automatic certification.

Scouting is capped at 10 skipped bases and 25 seconds by default. After an API
answer, both scouting controls, the base signature and loot are read again before
Next is clicked. The loop waits for a changed base before asking again. Existing
matchmaking, OCR calls and an in-flight API request may take time beyond the
search deadline; no further skip starts after it expires.

Deployment offers `legacy`, one validated concentrated point, or several
validated points distributed across cards. Legal points are rechecked before
deployment and after selecting each non-spell card. Slot restrictions and clan
exclusions still apply; Builder Base also honors `ATTACK_SLOT_RANGE`. Spell
targets retain the existing behavior. Builder Base card identities remain
unknown; its existing card/count scheme is not advertised as troop recognition.
No defense-aware, air-fan or Town Hall sniping strategy is inferred from missing
vision data.

## Evaluate results

Events are written to `debug/<instance>.jev.jsonl` (or the packaged application's
data directory), rotated at 5 MB with three backups. Logs include off-mode
upgrade outcomes for a baseline, observation provenance and quality, decisions,
fallback reasons, executed deployment points, search time and reported costs.
An upgrade is counted as successful only when the existing builder/lab checks
confirm it. Wall upgrades are unverified by builder-count changes.

```sh
python scripts/jev_evaluate.py debug/main.jev.jsonl
python scripts/jev_evaluate.py debug/main.jev.jsonl measured-outcomes.jsonl --instance main
```

The original bot closes/reopens CoC after deployment and does not read the battle
result. Offered loot is therefore logged as `loot_available`, **never as earned
loot**. To compare actual farming performance, add independently measured
battle-outcome rows (include search/battle/restart time in the duration):

```json
{"event":"battle_outcome","instance_id":"main","mode":"active","duration_seconds":120,"loot":{"gold":400000,"elixir":200000,"dark_elixir":4000}}
```

Without measured outcomes the report returns `null` for loot per minute. Compare
gold, elixir and dark elixir separately, along with search time, confirmed
upgrades, actual API costs and unknown-charge reservations. Compare similar
armies/accounts and report sample counts before adjusting confidence thresholds.
No improvement in loot, stars or trophies is claimed until measured.

## Verification

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Tests cover the documented API types, budget/failure paths, priority/discount
selection, real upgrade locator integration, confirmation checks, bounded
scouting, shadow mode, legal-area changes, slot restrictions and touch cleanup.
Screenshot regression fixtures are synthetic and do not validate live-game
recognition. No additional SDK, GPU or architecture-specific dependency is
required; the client uses the bot's existing `requests` dependency.

The suite also covers macOS startup and release configuration, BlueStacks
instance/ADB lookup, paths with spaces/quotes, accessibility-request wiring,
writable packaged-app logs, and key inheritance using real `spawn` processes.
Emulator launches, Cocoa/Accessibility calls and PyInstaller execution are
isolated in these tests. A native macOS-only test parses the produced sleep-helper
command with `osascript` without running it or requesting administrator access;
that test is skipped on Linux/Windows. Release CI runs the suite on its macOS and
Windows runners before packaging. None of this substitutes for an actual M4,
BlueStacks and gameplay test.
