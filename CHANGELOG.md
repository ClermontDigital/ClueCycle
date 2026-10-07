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
