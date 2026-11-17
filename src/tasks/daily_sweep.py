"""每日委托按高 / 中 / 低三档扫城。

从图1开始，一个地区一个地区看：先把所有高级做完，再从头扫一遍做中级，
最后再从头扫一遍做低级。一天最多 6 次；单条做完先不点「完成」。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src import config
from src.tasks.locations import (
    BEI_SERAM,
    LANGREN,
    LIANHU,
    LILITOS,
    LITRILE,
    MapPlace,
    NAN_SERAM,
    NAR,
    SAINT_CASARE,
    TURANDON,
)
from src.tasks.recipes import ALL_RECIPES, CommissionRecipe, CommissionTier

# 图6 暂定为圣卡萨雷斯：它是克里斯汀里还没在表上出现的那座城。若编号不对，改这里即可。
MAP_PLACES: tuple[tuple[int, MapPlace], ...] = (
    (1, LILITOS),
    (2, LIANHU),
    (3, BEI_SERAM),
    (4, NAN_SERAM),
    (5, LANGREN),
    (6, SAINT_CASARE),
    (7, NAR),
    (8, LITRILE),
    (9, TURANDON),
)

_PLACE_CHAPTER: dict[str, int] = {place.id: chapter for chapter, place in MAP_PLACES}
_PLACE_BY_ID: dict[str, MapPlace] = {place.id: place for _, place in MAP_PLACES}


def chapter_of(place: MapPlace | None) -> int | None:
    if place is None:
        return None
    return _PLACE_CHAPTER.get(place.id)


def map_label(chapter: int, place: MapPlace) -> str:
    # 王城莉莉托斯在表里常写成莉莉托斯。
    short = "莉莉托斯" if place.id == "lilitos" else place.name
    return f"图{chapter} {short}"


def recipes_in_sweep_order(tier: CommissionTier) -> tuple[CommissionRecipe, ...]:
    """某一档里，按图号从1到9，同一张图保持表中顺序。"""
    grouped: dict[int, list[CommissionRecipe]] = {}
    for recipe in ALL_RECIPES:
        if recipe.tier is not tier:
            continue
        chapter = chapter_of(recipe.location)
        if chapter is None:
            continue
        grouped.setdefault(chapter, []).append(recipe)
    ordered: list[CommissionRecipe] = []
    for chapter, _place in MAP_PLACES:
        ordered.extend(grouped.get(chapter, ()))
    return tuple(ordered)


def places_for_tier(tier: CommissionTier) -> tuple[tuple[int, MapPlace], ...]:
    """这一档需要查看的地区，仍按图1到图9，没有该档委托的图会跳过。"""
    wanted = {recipe.location.id for recipe in recipes_in_sweep_order(tier) if recipe.location}
    return tuple((chapter, place) for chapter, place in MAP_PLACES if place.id in wanted)


def sweep_plan_text() -> str:
    lines = [
        "每日委托按高 / 中 / 低三档扫城（原先叫优先 / 次级 / 最后）。",
        "从图1开始一个地区一个地区看：先做完所有高级，再从头扫中级，最后再扫低级。",
        f"一天最多 {config.DAILY_COMMISSION_CAP} 次；单条做完先不点「完成」，六次后用 --live --claim 一起领。",
        "「热情的冒险者」仍只打 9-7-1 三次，不用表里的 9-17-1。",
        "图6 暂按圣卡萨雷斯（表里还没有委托）；若编号不对，告诉我即可。",
        "",
    ]
    for tier in CommissionTier:
        lines.append(f"【{tier.zh_name}级】")
        current_chapter: int | None = None
        for recipe in recipes_in_sweep_order(tier):
            chapter = chapter_of(recipe.location)
            if chapter is None or recipe.location is None:
                continue
            if chapter != current_chapter:
                lines.append(f"  {map_label(chapter, recipe.location)}")
                current_chapter = chapter
            extra = f"：{recipe.stage_label}" if recipe.stage_label else ""
            pending = "（流程还没走查）" if recipe.flow == "pending" else ""
            lines.append(f"    - {recipe.name}{extra}{pending}")
        if current_chapter is None:
            lines.append("  （这一档还没有委托）")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def first_recipe_for_sweep() -> CommissionRecipe:
    high = recipes_in_sweep_order(CommissionTier.HIGH)
    if not high:
        raise RuntimeError("没有高级委托，无法开始扫城。")
    return high[0]


@dataclass
class SweepState:
    """当前扫到哪一档、哪一张图、已经做完几条。"""

    tier: CommissionTier = CommissionTier.HIGH
    place_id: str = LILITOS.id
    completed: int = 0
    # 这一档里已经在今天做过的 quest_id，避免同一条反复接。
    finished_ids: set[str] = field(default_factory=set)

    @classmethod
    def start(cls) -> "SweepState":
        first = first_recipe_for_sweep()
        place_id = first.location.id if first.location is not None else LILITOS.id
        return cls(tier=CommissionTier.HIGH, place_id=place_id)

    @property
    def place(self) -> MapPlace:
        return _PLACE_BY_ID[self.place_id]

    def travel_recipe(self) -> CommissionRecipe:
        """去当前地区用的配方：优先挑这一档、这一图里还没做的第一条。"""
        for recipe in recipes_in_sweep_order(self.tier):
            if recipe.location is not None and recipe.location.id == self.place_id:
                if recipe.quest_id not in self.finished_ids:
                    return recipe
        for recipe in recipes_in_sweep_order(self.tier):
            if recipe.location is not None and recipe.location.id == self.place_id:
                return recipe
        return first_recipe_for_sweep()

    def candidates_here(self) -> tuple[CommissionRecipe, ...]:
        return tuple(
            recipe
            for recipe in recipes_in_sweep_order(self.tier)
            if recipe.location is not None
            and recipe.location.id == self.place_id
            and recipe.quest_id not in self.finished_ids
        )

    def advance_place_or_tier(self) -> bool:
        """当前图这一档看完了。还有下一站则返回 True；三档都扫完返回 False。"""
        places = places_for_tier(self.tier)
        ids = [place.id for _, place in places]
        try:
            index = ids.index(self.place_id)
        except ValueError:
            index = -1
        if index + 1 < len(ids):
            self.place_id = ids[index + 1]
            return True
        if self.tier is CommissionTier.LOW:
            return False
        self.tier = CommissionTier(int(self.tier) + 1)
        nxt = places_for_tier(self.tier)
        if not nxt:
            return self.advance_place_or_tier() if self.tier is not CommissionTier.LOW else False
        self.place_id = nxt[0][1].id
        return True

    def mark_done(self, recipe: CommissionRecipe) -> None:
        self.finished_ids.add(recipe.quest_id)
        self.completed += 1

    def skip(self, recipe: CommissionRecipe) -> None:
        """这条今天做不了（例如背包里没有所需物品），不算占用每日次数。"""
        self.finished_ids.add(recipe.quest_id)

    def cap_reached(self) -> bool:
        return self.completed >= config.DAILY_COMMISSION_CAP
