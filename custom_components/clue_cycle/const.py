"""Constants for Clue Cycle."""
from __future__ import annotations

DOMAIN = "clue_cycle"

CONF_NAME = "name"
CONF_USERS = "users"            # HA user ids allowed to view and update this tracker
CONF_GOAL = "goal"              # conceive | track
CONF_CYCLE_LENGTH = "cycle_length"
CONF_PERIOD_LENGTH = "period_length"
CONF_LUTEAL_LENGTH = "luteal_length"

GOALS = ["conceive", "track"]

DEFAULT_CYCLE_LENGTH = 28
DEFAULT_PERIOD_LENGTH = 5
DEFAULT_LUTEAL_LENGTH = 14

CARD_FILENAME = "clue-cycle-card.js"
CARD_URL = f"/{DOMAIN}/{CARD_FILENAME}"

SIGNAL_UPDATED = f"{DOMAIN}_updated_{{}}"  # format with entry_id
