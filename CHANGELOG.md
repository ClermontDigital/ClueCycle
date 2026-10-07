## 0.5.0

- **Daily reminder.** "How do you feel today?" at a set time (12:00 by default), like Clue's. Tapping
  it opens the tracker on the Track tab, and by default it's skipped once something is logged that
  day. Anyone who can edit the tracker can set it up.
- **"The owner's phones"** as a recipient for every notification. It's worked out each time a
  notification is sent, covers phones and tablets but not Macs, and includes phones signed in later.
- **Admins** can switch on the owner's cycle notifications and daily reminder in the integration's
  options. These only go to the owner's own phones.
- The card opens on the Track tab when its address ends in `?cc_view=track`.

## 0.4.1

- The compact widget no longer repeats the next period when the ring's own line already mentions it.
  It shows the fertile window instead.

## 0.4.0

- **Track is easier to get around.** Each category folds down to one row that shows what's logged
  that day. Tap it to open the chips. Period, and anything logged that day, start open, and there's
  Expand all and Collapse all.
- **Edit categories**, like Clue's tracking options. Hide the categories you don't use and change the
  order of the rest. Hidden ones move to "More categories" at the bottom, so nothing is lost. The
  layout is saved on the tracker, so it's the same for everyone who logs.
- **A compact widget** (`view: mini`) for other dashboards: a small ring, the headline and the next
  milestone. Tapping it can open the full tracker. There's a `glass` theme for tron-style dashboards.

## 0.3.0

- **Fertility treatment (optional).** Covers IVF, frozen embryo transfer, IUI, egg freezing and
  ovulation induction. The owner turns it on in Settings, which adds a Treatment tab and a Treatment
  section on Track.
  - **Treatment cycles** have a type, protocol, embryo day, blood test date and outcome. While one
    runs, natural predictions pause and the ring follows the treatment: stimulation days, the
    trigger, egg collection and transfer markers, and the wait to the blood test. Treatment cycles
    are left out of the natural averages.
  - **Logging:** procedure chips, medicine doses (dose, unit, time) and results (follicles, lining,
    hormone levels, egg and embryo numbers, hCG). Medicines common in Australian clinics are built
    in, and you can add your own.
  - **Dose reminders:** a phone notification with Done and Snooze buttons. Done logs the dose. If
    nothing has been logged 30 minutes later, it asks once more.
  - **Summary for your clinic:** each medicine's days and total dose, the key dates and the results,
    with Copy and Print.
- **Cycle notifications.** Once a day, if your phase has changed, the ring's headline goes to your
  phone. There's a discreet mode.
- Notifications only go to the phones of people who can see the tracker. That's checked again on
  every send.
- The Log tab is now called **Track**, as in Clue. `view: track` works in the card config, and
  `log` still does.
- **Sex and sex drive** now sits directly under Period.

## 0.2.0

- **Imports Clue's current "Download my data" zip.** The zip is password protected, so the card now
  asks for the password from Clue's email. Only `measurements.json` is read from it.
- **Categories and options now use the names in Clue's export.** For example, Pain is now Period
  cramps, Headache, Migraine, Ovulation pain, Tender breasts, Lower back and Joint. Energy is now
  Fully energised, Energetic, Tired and Exhausted. Feelings adds Fine, Mood swings, Insecure, Not in
  control, Indifferent, Grateful and Excited. There are also new options for Digestion, Poop, Sex,
  Hair and Medication. The old names are still accepted when importing.
- **New categories:** Birth control (pill taken, late, missed or doubled, and shot), Sleep quality,
  Party, Leisure and Appointments.
- **Imported sleep durations** go into Clue's 0-3, 3-6, 6-9 and 9+ hour buckets. Wearable data and
  weight are listed as not tracked rather than unrecognised.
- **Tracking gaps** longer than 90 days show as a gap in the cycle history and are left out of the
  averages, so years of patchy tracking can't skew the predictions.

## 0.1.1

- Packaging only, no behaviour changes. The manifest keys are now in the order hassfest expects,
  `hacs.json` only has the keys HACS currently accepts, and LICENSE is the standard Apache-2.0 text,
  so GitHub detects it. The 0.1.0 tag was cut before these fixes, so its validation run failed.

## 0.1.0

- First release.
- **The cycle ring.** Shows the current cycle day, the period, the predicted period, the fertile
  window, peak days and ovulation, with coloured dots for logged days. The middle shows Clue-style
  headlines and tips for each phase.
- **Daily log.** Uses Clue's categories, with "My tags" and a note for each day. Any day, past or
  future, can be logged, and each day records who last changed it.
- **Calendar, analysis and predictions.** The calendar shows logged and predicted periods, the
  fertile window and ovulation. Analysis covers cycle length, variation, period length, flow per
  cycle and cycle history. Predictions use the last six cycles.
- **Import from Clue.** Reads the legacy `.cluedata` export and the newer measurements export,
  as JSON or zipped. It shows a preview before saving anything.
- **Multi-user and private by default.** Each tracker has an owner. The owner can share it with
  other Home Assistant users as view-only or editable, and nobody else can see it.
- **Optional sensors.** Sensors, binary sensors and a calendar are available for automations. They
  are off by default because entities are visible to every Home Assistant user.
