"""Who can see and change a tracker.

A tracker belongs to one Home Assistant user (its owner) and is private by default. The owner
chooses who else may see it, and whether each of them can only view or can also edit. Every
WebSocket call goes through ``role_for`` before it touches any data.
"""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry

CONF_OWNER = "owner"
CONF_SHARING = "sharing"            # {user_id: "view" | "edit"}
CONF_EXPOSE = "expose_entities"     # create HA sensors (visible to every HA user and in history)

ROLE_OWNER = "owner"
ROLE_EDIT = "edit"
ROLE_VIEW = "view"
SHARE_LEVELS = (ROLE_VIEW, ROLE_EDIT)


def owner_of(entry: ConfigEntry) -> str | None:
    return entry.data.get(CONF_OWNER)


def sharing_of(entry: ConfigEntry) -> dict[str, str]:
    raw = entry.options.get(CONF_SHARING) or {}
    return {uid: lvl for uid, lvl in raw.items() if lvl in SHARE_LEVELS}


def role_for(entry: ConfigEntry, user_id: str | None) -> str | None:
    """The caller's role on this tracker, or None if they can't see it at all."""
    if not user_id:
        return None
    if user_id == owner_of(entry):
        return ROLE_OWNER
    return sharing_of(entry).get(user_id)


def can_edit(role: str | None) -> bool:
    return role in (ROLE_OWNER, ROLE_EDIT)


def describe(entry: ConfigEntry, role: str) -> dict[str, Any]:
    """What the card needs to list a tracker for this caller."""
    return {
        "entry_id": entry.entry_id,
        "name": entry.title,
        "role": role,
        "owner": owner_of(entry),
    }
