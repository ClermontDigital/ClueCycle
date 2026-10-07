"""Tracking categories, modelled on the categories in the Clue app.

Each category has a stable id (used in storage and in the Clue import mapping), a label, a
colour for its chips and its dots on the cycle ring, an mdi icon, and its options. ``single``
categories take one option per day (period flow, sleep); the rest take any number.
"""
from __future__ import annotations

from typing import Any

# Period flow, lightest to heaviest. Spotting is logged but never starts or extends a period.
FLOW_LEVELS: dict[str, int] = {"light": 1, "medium": 2, "heavy": 3, "super_heavy": 4}
SPOTTING = "spotting"


def _opt(option_id: str, label: str, icon: str) -> dict[str, str]:
    return {"id": option_id, "label": label, "icon": icon}


CATEGORIES: list[dict[str, Any]] = [
    {
        "id": "period", "label": "Period", "color": "#E8473F", "icon": "mdi:water", "single": True,
        "options": [
            _opt("light", "Light", "mdi:water-outline"),
            _opt("medium", "Medium", "mdi:water"),
            _opt("heavy", "Heavy", "mdi:water-plus"),
            _opt("super_heavy", "Super heavy", "mdi:waves"),
            _opt("spotting", "Spotting", "mdi:circle-small"),
        ],
    },
    {
        "id": "collection", "label": "Collection method", "color": "#C2353B", "icon": "mdi:water-check",
        "options": [
            _opt("tampon", "Tampon", "mdi:pill"),
            _opt("pad", "Pad", "mdi:rectangle-outline"),
            _opt("panty_liner", "Panty liner", "mdi:minus-box-outline"),
            _opt("cup", "Cup", "mdi:cup-outline"),
            _opt("period_underwear", "Period underwear", "mdi:tshirt-crew-outline"),
        ],
    },
    {
        "id": "feelings", "label": "Feelings", "color": "#E05C8A", "icon": "mdi:emoticon-outline",
        "options": [
            _opt("happy", "Happy", "mdi:emoticon-happy-outline"),
            _opt("sensitive", "Sensitive", "mdi:emoticon-neutral-outline"),
            _opt("sad", "Sad", "mdi:emoticon-sad-outline"),
            _opt("pms", "PMS", "mdi:emoticon-angry-outline"),
            _opt("anxious", "Anxious", "mdi:emoticon-confused-outline"),
            _opt("irritable", "Irritable", "mdi:emoticon-frown-outline"),
        ],
    },
    {
        "id": "pain", "label": "Pain", "color": "#D9577F", "icon": "mdi:lightning-bolt-outline",
        "options": [
            _opt("cramps", "Cramps", "mdi:lightning-bolt"),
            _opt("headache", "Headache", "mdi:head-alert-outline"),
            _opt("ovulation_pain", "Ovulation pain", "mdi:circle-slice-3"),
            _opt("tender_breasts", "Tender breasts", "mdi:heart-outline"),
            _opt("back_pain", "Back pain", "mdi:human-handsdown"),
        ],
    },
    {
        "id": "energy", "label": "Energy", "color": "#2EA77A", "icon": "mdi:battery-charging-outline",
        "options": [
            _opt("energized", "Energised", "mdi:battery-charging-high"),
            _opt("high", "High energy", "mdi:battery-high"),
            _opt("low", "Low energy", "mdi:battery-low"),
            _opt("exhausted", "Exhausted", "mdi:battery-alert-variant-outline"),
        ],
    },
    {
        "id": "sleep", "label": "Sleep", "color": "#4A7BD0", "icon": "mdi:sleep", "single": True,
        "options": [
            _opt("0_3", "0-3 hrs", "mdi:clock-time-three-outline"),
            _opt("3_6", "3-6 hrs", "mdi:clock-time-six-outline"),
            _opt("6_9", "6-9 hrs", "mdi:clock-time-nine-outline"),
            _opt("9_plus", "9+ hrs", "mdi:clock-time-twelve-outline"),
        ],
    },
    {
        "id": "mind", "label": "Mind", "color": "#F07B3F", "icon": "mdi:brain",
        "options": [
            _opt("forgetful", "Forgetful", "mdi:head-question-outline"),
            _opt("brain_fog", "Brain fog", "mdi:weather-fog"),
            _opt("calm", "Calm", "mdi:meditation"),
            _opt("stressed", "Stressed", "mdi:head-flash-outline"),
            _opt("focused", "Focused", "mdi:target"),
            _opt("distracted", "Distracted", "mdi:head-dots-horizontal-outline"),
            _opt("motivated", "Motivated", "mdi:arm-flex-outline"),
            _opt("unmotivated", "Unmotivated", "mdi:bed-outline"),
            _opt("creative", "Creative", "mdi:lightbulb-on-outline"),
            _opt("productive", "Productive", "mdi:chart-line-variant"),
            _opt("unproductive", "Unproductive", "mdi:chart-line-stacked"),
        ],
    },
    {
        "id": "social", "label": "Social life", "color": "#F07B3F", "icon": "mdi:account-group-outline",
        "options": [
            _opt("sociable", "Sociable", "mdi:chat-outline"),
            _opt("withdrawn", "Withdrawn", "mdi:chat-remove-outline"),
            _opt("supportive", "Supportive", "mdi:hand-heart-outline"),
            _opt("argumentative", "Argumentative", "mdi:chat-alert-outline"),
        ],
    },
    {
        "id": "cravings", "label": "Cravings", "color": "#F07B3F", "icon": "mdi:food-outline",
        "options": [
            _opt("sweet", "Sweet", "mdi:candy-outline"),
            _opt("salty", "Salty", "mdi:shaker-outline"),
            _opt("greasy", "Greasy", "mdi:french-fries"),
            _opt("carbs", "Carbs", "mdi:bread-slice-outline"),
            _opt("chocolate", "Chocolate", "mdi:cupcake"),
        ],
    },
    {
        "id": "digestion", "label": "Digestion", "color": "#B5895A", "icon": "mdi:stomach",
        "options": [
            _opt("great", "Great digestion", "mdi:check-circle-outline"),
            _opt("bloated", "Bloated", "mdi:circle-expand"),
            _opt("nauseated", "Nauseated", "mdi:emoticon-sick-outline"),
            _opt("gassy", "Gassy", "mdi:weather-windy"),
        ],
    },
    {
        "id": "poop", "label": "Poop", "color": "#9C6B3E", "icon": "mdi:toilet",
        "options": [
            _opt("great", "Great", "mdi:check-circle-outline"),
            _opt("normal", "Normal", "mdi:circle-outline"),
            _opt("constipated", "Constipated", "mdi:close-circle-outline"),
            _opt("diarrhea", "Diarrhoea", "mdi:water-alert-outline"),
        ],
    },
    {
        "id": "discharge", "label": "Discharge", "color": "#5FB3C8", "icon": "mdi:water-opacity",
        "options": [
            _opt("none", "None", "mdi:circle-off-outline"),
            _opt("sticky", "Sticky", "mdi:water-outline"),
            _opt("creamy", "Creamy", "mdi:water"),
            _opt("egg_white", "Egg white", "mdi:egg-outline"),
            _opt("atypical", "Atypical", "mdi:alert-circle-outline"),
        ],
    },
    {
        "id": "sex", "label": "Sex and sex drive", "color": "#8A6BD8", "icon": "mdi:heart-multiple-outline",
        "options": [
            _opt("protected", "Protected sex", "mdi:shield-heart-outline"),
            _opt("unprotected", "Unprotected sex", "mdi:heart-outline"),
            _opt("withdrawal", "Withdrawal", "mdi:heart-half-outline"),
            _opt("high_drive", "High sex drive", "mdi:fire"),
            _opt("low_drive", "Low sex drive", "mdi:snowflake"),
            _opt("masturbation", "Masturbation", "mdi:heart-circle-outline"),
        ],
    },
    {
        "id": "tests", "label": "Tests", "color": "#5B8DEF", "icon": "mdi:test-tube",
        "options": [
            _opt("ovulation_positive", "Ovulation test +", "mdi:plus-circle-outline"),
            _opt("ovulation_negative", "Ovulation test -", "mdi:minus-circle-outline"),
            _opt("pregnancy_positive", "Pregnancy test +", "mdi:plus-box-outline"),
            _opt("pregnancy_negative", "Pregnancy test -", "mdi:minus-box-outline"),
        ],
    },
    {
        "id": "skin", "label": "Skin", "color": "#E8A33D", "icon": "mdi:face-woman-shimmer-outline",
        "options": [
            _opt("good", "Good skin", "mdi:star-four-points-outline"),
            _opt("oily", "Oily", "mdi:water-outline"),
            _opt("dry", "Dry", "mdi:texture"),
            _opt("acne", "Acne", "mdi:dots-hexagon"),
        ],
    },
    {
        "id": "hair", "label": "Hair", "color": "#E8A33D", "icon": "mdi:hair-dryer-outline",
        "options": [
            _opt("good", "Good hair", "mdi:star-four-points-outline"),
            _opt("bad", "Bad hair", "mdi:emoticon-frown-outline"),
            _opt("oily", "Oily", "mdi:water-outline"),
            _opt("dry", "Dry", "mdi:texture"),
        ],
    },
    {
        "id": "exercise", "label": "Exercise", "color": "#3DA5D9", "icon": "mdi:run",
        "options": [
            _opt("running", "Running", "mdi:run"),
            _opt("cycling", "Cycling", "mdi:bike"),
            _opt("yoga", "Yoga", "mdi:yoga"),
            _opt("swimming", "Swimming", "mdi:swim"),
            _opt("walking", "Walking", "mdi:walk"),
            _opt("gym", "Gym", "mdi:dumbbell"),
        ],
    },
    {
        "id": "ailments", "label": "Ailments", "color": "#9AA0A6", "icon": "mdi:emoticon-sick-outline",
        "options": [
            _opt("cold_flu", "Cold or flu", "mdi:snowflake-thermometer"),
            _opt("allergy", "Allergy", "mdi:flower-pollen-outline"),
            _opt("fever", "Fever", "mdi:thermometer-high"),
            _opt("injury", "Injury", "mdi:bandage"),
        ],
    },
    {
        "id": "medication", "label": "Medication", "color": "#9AA0A6", "icon": "mdi:pill",
        "options": [
            _opt("painkiller", "Painkiller", "mdi:pill"),
            _opt("antihistamine", "Antihistamine", "mdi:pill-multiple"),
            _opt("cold_flu_meds", "Cold or flu meds", "mdi:medical-bag"),
            _opt("antibiotic", "Antibiotic", "mdi:bottle-tonic-plus-outline"),
        ],
    },
]

TAG_COLOR = "#8E8E93"
CATEGORY_IDS = {c["id"] for c in CATEGORIES}
CATEGORY_BY_ID = {c["id"]: c for c in CATEGORIES}


def option_ids(category_id: str) -> set[str]:
    """Return the option ids a built-in category accepts."""
    cat = CATEGORY_BY_ID.get(category_id)
    return {o["id"] for o in cat["options"]} if cat else set()


def is_single(category_id: str) -> bool:
    """True when a category takes one option per day."""
    return bool(CATEGORY_BY_ID.get(category_id, {}).get("single"))
