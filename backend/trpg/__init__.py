"""跑团引擎（阶段B）：角色卡 / 骰子检定 / AI主持人 / 成长 / 篇章推进。

与 engine/（治理引擎）平级，不侵入治理结算逻辑。
"""
from . import chapter, character, dice, gm, modifiers, writeback

__all__ = ["chapter", "character", "dice", "gm", "modifiers", "writeback"]
