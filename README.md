# Clue Cycle - a private cycle tracker for Home Assistant

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![HACS Badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![Version](https://img.shields.io/badge/version-0.1.1-green.svg)](https://github.com/ClermontDigital/ClueCycle)

A period and cycle tracker that looks and works like the Clue app, where every bit of data stays in
your own Home Assistant. It has the cycle ring, daily logging with the same categories and tags,
predictions for the next period and the fertile window, and Clue's analysis screens. You can bring
your history across from a Clue data export.

> **Unofficial.** Clue Cycle is not made by, affiliated with or endorsed by Clue or BioWink GmbH.
> "Clue" is used only to describe what it imitates.
>
> **Not medical advice, and not contraception.** Predictions are estimates from your logged history.
> Don't use them to prevent pregnancy. Talk to a doctor about anything that worries you.

## Features

- ⭕ **The cycle ring.** Today's cycle day sits on a ring that shows your period, predicted period,
  fertile window, peak days and estimated ovulation. Each logged day carries coloured dots. The
  middle says where you are, for example "Good timing to try to conceive" or "Period expected in 3 days",
  with tips for that phase.
- 📝 **Daily log, Clue style.** Period flow and collection method, feelings, pain, energy, sleep,
  mind, social life, cravings, digestion, poop, discharge, sex and sex drive, tests, skin, hair,
  exercise, ailments and medication. You also get your own **tags** and a note for each day.
  Logging works for any day, past or future.
- 📅 **Calendar.** A month view with logged and predicted periods, the fertile window and ovulation.
- 📊 **Analysis.** Cycle length (and how many recent cycles were typical), cycle variation,
  average period length, period flow per cycle, and cycle history.
- 🔮 **Predictions.** Predictions come from the last six cycles, the way Clue does it. The next
  period uses your average cycle length. The fertile window is built from your shortest and longest
  cycles. Ovulation is one luteal phase (14 days, adjustable) before the next period. A late period
  is shown as late; the cycle is not silently moved.
- 📥 **Import from Clue.** Choose the export file in the card. You'll see a preview of what will
  come across before anything is saved.
- 👥 **Multi-user, private by default.** See [Privacy and sharing](#privacy-and-sharing).
- 🔔 **Optional sensors and a calendar** for automations, such as a reminder the day before your
  period is due. They are off by default, for a reason explained below.
- 🚀 **HACS ready.** No YAML, no add-on, no cloud, no extra database.

## Screenshots

These were made with made-up history, not anyone's real data.

**Today.** The ring shows where you are in your cycle, with the next period, the fertile window and
ovulation underneath. Tap the day marker, or "How do you feel today?", to log.

![The cycle ring](images/today.png)

**Logging a day.** Use the day strip to pick any day. Tap the chips to log, the same way as in Clue.

![Logging a day](images/log.png)

**Calendar.**

![Calendar](images/calendar.png)

**Analysis.**

![Analysis](images/analysis.png)

## Installation

### Requirements
- Home Assistant 2025.1 or newer
- HACS, for the easy route

### HACS
1. In HACS, open the menu and choose **Custom repositories**. Add
   `https://github.com/ClermontDigital/ClueCycle` with the category **Integration**.
2. Install **Clue Cycle**, then restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration → Clue Cycle**.

### Manual
Copy `custom_components/clue_cycle/` into `/config/custom_components/` and restart Home Assistant.

### Adding a tracker
Each person gets their own tracker. When you add the integration, you choose:

- **Name.** It's shown on the card, for example "Alex's cycle".
- **Owner.** This is the Home Assistant user the tracker belongs to. Only the owner can change
  its settings or decide who else sees it.
- **Goal.** *Trying to conceive* or *Track my cycle*. This changes the wording on the ring.
- **Usual cycle and period length.** These are used only until a few cycles have been logged or
  imported.

### The card
The integration serves its own card and registers it as a dashboard resource for you. Add it to
any dashboard:

```yaml
type: custom:clue-cycle-card
```

| Option     | Default   | Description                                                                 |
|------------|-----------|-----------------------------------------------------------------------------|
| `entry_id` | first one | Which tracker to open, if the person viewing can see more than one.         |
| `view`     | `today`   | The tab to open on: `today`, `log`, `calendar`, `analysis` or `settings`.   |

The card works best in a **Panel** view, or a Sections view with the card set to full width.

## Privacy and sharing

Cycle data is personal, so Clue Cycle is careful about who can see it:

- **Private by default.** A new tracker is visible only to its owner. That includes other
  Home Assistant administrators: everything goes through the integration's own API, which checks
  who is asking on every request.
- **The owner chooses who else sees it.** They do this in the card's **Settings → Who can see this**.
  Every other user can be set to:
  - **Hidden.** The tracker doesn't exist for them.
  - **Can view.** They see the ring, the log, the calendar and the analysis, but can't change anything.
  - **Can edit.** They can also log days, manage tags and import. Use this for a partner who logs on
    your behalf. Each day records who last changed it.
- **Only the owner changes settings or sharing.** Someone with edit access can't share the tracker
  further or change the cycle settings.
- **Sensors are off by default.** Home Assistant entities are visible to every user, and their
  state is kept in history, so they are opt-in. When the owner turns them on, the tracker adds the
  entities listed below.
- **Storage.** Data is kept in Home Assistant's `.storage/clue_cycle.<entry_id>` and is included
  in your Home Assistant backups. Deleting the tracker deletes its data.

Asking about a tracker you can't see returns the same answer as asking about one that doesn't
exist, so other users can't even find out that it's there.

What this can't protect against: anyone with access to the Home Assistant host's files or backups
can read the storage file. Administrators can also see that a tracker exists under
**Devices & services**, and can change its usual lengths there, though not its data or sharing.
Choose who has admin and host access accordingly.

## Sensors and calendar (optional)

These are created only when the owner turns on **Home Assistant sensors** in the card's settings:

| Entity | What it is |
|---|---|
| `sensor.<name>_cycle_day` | Day of the current cycle |
| `sensor.<name>_cycle_phase` | `period`, `follicular`, `fertile`, `fertile_peak`, `ovulation`, `luteal`, `pms`, `due`, `late` |
| `sensor.<name>_next_period` | Date the next period is expected |
| `sensor.<name>_days_until_period` | Days until then |
| `sensor.<name>_ovulation` | Estimated ovulation date |
| `sensor.<name>_fertile_window_start` / `_end` | The fertile window |
| `sensor.<name>_average_cycle_length` | Over the last six cycles |
| `sensor.<name>_average_period_length` | Over the last six periods |
| `sensor.<name>_cycle_variation` | Longest minus shortest of the last six cycles |
| `binary_sensor.<name>_on_period` | On during a period |
| `binary_sensor.<name>_fertile_window` | On during the fertile window |
| `calendar.<name>_cycle` | Logged and predicted periods, fertile windows and ovulation |

They update as soon as anything is logged, and again at midnight.

## Importing from Clue

1. In the Clue app, go to **Settings → Data export** and request an export. Clue emails a file,
   or it may arrive as a `.zip`.
2. In the card, open **Settings → Import from Clue** and choose the file. Both the older
   `.cluedata` format and the newer measurements export work, as JSON or zipped.
3. Check the preview. It shows how many days, the date range, how many tags, and any categories
   it didn't recognise. Then press **Import**.

Importing merges into what's already there, day by day, and imported values win. You can run it
again safely. The file is sent from your browser to Home Assistant over the existing authenticated
connection and is never written to disk.

## How predictions work

- A **period** is a run of days logged with light, medium, heavy or super heavy flow. Gaps of up
  to two days are allowed. Spotting doesn't start or extend a period.
- A **cycle** runs from the first day of one period to the day before the next.
- The **averages** use your last six complete cycles. Until you have some, your usual lengths from
  settings are used.
- **Typical ranges** follow Clue: a cycle of 21 to 35 days, a period of 2 to 7 days, and a
  variation of up to 7 days.
- **Ovulation** is estimated as cycle start + (average cycle length − luteal phase).
- The **fertile window** runs from 5 days before the earliest likely ovulation, using your shortest
  recent cycle, to 1 day after the latest, using your longest. Peak fertility is the two days before
  ovulation and ovulation itself.
- Past cycles get an **estimated ovulation** from when the next period actually started.

## WebSocket API

The card talks to Home Assistant only through these commands, and each one checks the caller's
role. They're documented here for anyone building something else on top.

| Command | Role | Purpose |
|---|---|---|
| `clue_cycle/trackers` | any | Trackers the caller can see, and their role on each |
| `clue_cycle/categories` | any | The logging categories and options |
| `clue_cycle/overview` | view | Ring, prediction, status, stats and tags |
| `clue_cycle/days` | view | Day logs between two dates |
| `clue_cycle/calendar` | view | Per-day colouring between two dates (max 400 days) |
| `clue_cycle/analysis` | view | Stats and every cycle |
| `clue_cycle/subscribe` | view | Pushes an event whenever the tracker changes |
| `clue_cycle/set_day` | edit | Log or clear values on a day |
| `clue_cycle/tag_add` / `tag_remove` | edit | Manage "My tags" |
| `clue_cycle/import` | edit | Import a Clue export (`dry_run` for a preview) |
| `clue_cycle/settings_set` | owner | Goal and usual lengths |
| `clue_cycle/sharing` / `sharing_set` | owner | Who can see or edit, and whether sensors are on |

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest -q
```

The card is a single buildless file, `custom_components/clue_cycle/www/clue-cycle-card.js`. The
cycle maths lives in `engine.py`, which is plain Python and has no Home Assistant imports.

## Issues and contributions

Bugs and ideas go in the [issue tracker](https://github.com/ClermontDigital/ClueCycle/issues).
**Please don't attach your own export or screenshots that show real cycle data.**

## License

Apache 2.0. See [LICENSE](LICENSE).
