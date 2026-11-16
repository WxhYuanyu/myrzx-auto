from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.vision.image import load_bgr  # noqa: E402
from src.vision.templates import load_templates  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "screens"
WALKTHROUGH_DIR = ROOT / "tests" / "fixtures" / "walkthrough"
TURN_IN_DIR = ROOT / "tests" / "fixtures" / "turn_in"

SCREEN_FILES = {
    "world": FIXTURE_DIR / "01_world_allgreen.png",
    "city": FIXTURE_DIR / "02_city_lilitos.png",
    "association": FIXTURE_DIR / "03_association_interior.png",
    "commission": FIXTURE_DIR / "04_commission_center.png",
    "quest_detail": FIXTURE_DIR / "05_quest_detail.png",
    "city_explore": FIXTURE_DIR / "06_city_explore_nav.png",
    "stage_map": FIXTURE_DIR / "07_stage_map_1x.png",
    "stage_1_3": FIXTURE_DIR / "08_stage_1_3.png",
    "explore_bubble": FIXTURE_DIR / "09_explore_bubble.png",
}

WALKTHROUGH_FILES = {
    "wt_world_south": WALKTHROUGH_DIR / "01_world_south.png",
    "wt_world_lilitos": WALKTHROUGH_DIR / "02_world_lilitos.png",
    "wt_city": WALKTHROUGH_DIR / "03_city.png",
    "wt_association": WALKTHROUGH_DIR / "04_association.png",
    "wt_commission_list": WALKTHROUGH_DIR / "05_commission_list.png",
    "wt_quest_detail": WALKTHROUGH_DIR / "06_quest_detail.png",
    "wt_after_accept_toast": WALKTHROUGH_DIR / "07_after_accept_toast.png",
    "wt_after_accept": WALKTHROUGH_DIR / "08_after_accept.png",
    "wt_list_after_accept": WALKTHROUGH_DIR / "09_list_after_accept.png",
    "wt_association_leave": WALKTHROUGH_DIR / "10_association_leave.png",
    "wt_city_explore": WALKTHROUGH_DIR / "11_city_explore.png",
    "wt_stage_map": WALKTHROUGH_DIR / "12_stage_map.png",
    "wt_stage_1_3_npc": WALKTHROUGH_DIR / "13_stage_1_3_npc.png",
    "wt_story_dialog": WALKTHROUGH_DIR / "14_story_dialog.png",
    "wt_battle": WALKTHROUGH_DIR / "15_battle.png",
    "wt_victory": WALKTHROUGH_DIR / "16_victory.png",
    "wt_post_story": WALKTHROUGH_DIR / "17_post_story.png",
    "wt_stage_quest_done": WALKTHROUGH_DIR / "18_stage_quest_done.png",
    "wt_quest_log": WALKTHROUGH_DIR / "19_quest_log.png",
    "wt_quest_finish": WALKTHROUGH_DIR / "20_quest_finish.png",
    "wt_loot": WALKTHROUGH_DIR / "21_loot.png",
    "wt_quest_log_done": WALKTHROUGH_DIR / "22_quest_log_done.png",
}

WALKTHROUGH_ORDER = list(WALKTHROUGH_FILES.keys())

TURN_IN_FILES = {
    "region": TURN_IN_DIR / "01_region_crystia.png",
    "commission": TURN_IN_DIR / "02_commission_list.png",
    "after_accept": TURN_IN_DIR / "03_after_accept.png",
    "city_npc": TURN_IN_DIR / "04_city_npc.png",
    "story": TURN_IN_DIR / "05_story.png",
    "city_scroll": TURN_IN_DIR / "06_city_scroll.png",
    "quest_finish": TURN_IN_DIR / "07_quest_finish.png",
    "loot": TURN_IN_DIR / "08_loot.png",
}

TURN_IN_ORDER = list(TURN_IN_FILES.keys())


@pytest.fixture(scope="session")
def templates():
    return load_templates()


@pytest.fixture(scope="session")
def screens():
    return {name: load_bgr(path) for name, path in SCREEN_FILES.items()}


@pytest.fixture(scope="session")
def walkthrough():
    return {name: load_bgr(path) for name, path in WALKTHROUGH_FILES.items()}


@pytest.fixture(scope="session")
def turn_in():
    return {name: load_bgr(path) for name, path in TURN_IN_FILES.items()}
