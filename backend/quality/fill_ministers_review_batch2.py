# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

REVIEW_PATH = Path(__file__).resolve().parents[1] / "data" / "ministers_review.json"
REVIEW_DATE = "2026-02-20"

COMMON_SOURCES = [
    {
        "title": "《明史》总目（维基文库）",
        "url": "https://zh.wikisource.org/wiki/%E6%98%8E%E5%8F%B2",
        "tier": "A_PRIMARY",
        "locator": "全书卷目索引，待补各人物具体卷次",
    },
    {
        "title": "《明史/卷72（職官一）》",
        "url": "https://zh.wikisource.org/wiki/%E6%98%8E%E5%8F%B2/%E5%8D%B772",
        "tier": "A_PRIMARY",
        "locator": "官职名称与机构口径校验",
    },
    {
        "title": "China Biographical Database Project (CBDB) 首页",
        "url": "https://cbdb.hsites.harvard.edu/",
        "tier": "B_DATABASE",
        "locator": "人物生平与仕历待逐条核定",
    },
    {
        "title": "项目初始大臣数据（ministers.json）",
        "url": "backend/data/ministers.json",
        "tier": "C_SECONDARY",
        "locator": "当前项目设定基线",
    },
]

BATCH2_UPDATES = {
    "施凤来": {
        "aliases": ["施鳳來"],
        "office_history": ["武英殿大学士", "阉党时期阁臣"],
        "major_contributions": [
            "阉党时期在内阁任职，参与中枢文书与票拟流程。",
            "崇祯即位后退出中枢，反映旧阁臣更替。",
        ],
        "related_events": ["崇祯初阉党清算", "内阁人员重组"],
        "project_role_background": "旧秩序遗留阁臣，可作为“清算/宽纵”政策影响样本。",
    },
    "张瑞图": {
        "aliases": ["張瑞圖"],
        "office_history": ["建极殿大学士", "阉党时期阁臣"],
        "major_contributions": [
            "以阁臣身份参与中枢决策与文书工作。",
            "因涉阉党政治在崇祯初去职，体现政治追责链条。",
        ],
        "related_events": ["阉党专政", "崇祯初逆案处理"],
        "project_role_background": "兼具文化名望与政治争议的角色，可触发名望与信誉冲突事件。",
    },
    "阮大铖": {
        "aliases": ["阮大鋮"],
        "office_history": ["太常少卿", "阉党系文臣"],
        "major_contributions": [
            "阉党时期参与朝局运作并形成争议政治标签。",
            "后期在南明再度活跃，体现人物政治立场波动。",
        ],
        "related_events": ["崇祯初阉党清算", "南明朝局分化"],
        "project_role_background": "高争议文臣角色，适合建模“名声-实用”两难决策。",
    },
    "李永贞": {
        "aliases": ["李永貞"],
        "office_history": ["司礼监太监", "魏忠贤心腹内臣"],
        "major_contributions": [
            "阉党时期作为内廷执行层参与权力网络运作。",
            "崇祯初被清算，成为内廷整肃对象之一。",
        ],
        "related_events": ["阉党专权", "崇祯初内廷整肃"],
        "project_role_background": "阉党执行节点角色，影响内廷风险与朝臣恐惧值。",
    },
    "朱纯臣": {
        "aliases": [],
        "office_history": ["成国公", "掌京营（后期）"],
        "major_contributions": [
            "作为勋贵集团代表长期参与京营权力结构。",
            "甲申之变中的政治选择对明廷威望造成冲击。",
        ],
        "related_events": ["京营整饬争论", "甲申之变"],
        "project_role_background": "勋贵军事资源节点，可影响京师防务执行力度。",
    },
    "张维贤": {
        "aliases": ["張維賢"],
        "office_history": ["英国公", "勋贵集团核心"],
        "major_contributions": [
            "在崇祯初政治过渡阶段维持勋贵体系稳定。",
            "代表传统勋贵与文官系统之间的协调关系。",
        ],
        "related_events": ["崇祯即位初期权力重组", "京营权责调整"],
        "project_role_background": "勋贵稳定器角色，可降低短期军政震荡。",
    },
    "徐允祯": {
        "aliases": ["徐允禎"],
        "office_history": ["定国公", "勋贵集团成员"],
        "major_contributions": [
            "参与勋贵集团对京营和朝局的传统影响。",
            "甲申之变中的立场变化体现勋贵体系脆弱性。",
        ],
        "related_events": ["勋贵集团权力分配", "甲申之变"],
        "project_role_background": "中低忠诚勋贵样本，可用于“战时服从度”机制。",
    },
    "巩永固": {
        "aliases": [],
        "office_history": ["驸马都尉", "皇亲勋贵"],
        "major_contributions": [
            "以皇亲身份连接内廷与勋贵体系。",
            "甲申之变中殉国，体现勋贵内部忠节分化。",
        ],
        "related_events": ["崇祯朝皇亲政治", "甲申之变"],
        "project_role_background": "高忠诚皇亲角色，利于提升危机情境下朝廷凝聚度。",
    },
    "刘文炳": {
        "aliases": ["劉文炳"],
        "office_history": ["新城侯", "勋贵外戚系统"],
        "major_contributions": [
            "以外戚勋贵身份参与朝廷军事与礼制网络。",
            "甲申之变中殉国，代表部分勋贵的忠君选择。",
        ],
        "related_events": ["勋贵与外戚互动", "甲申之变"],
        "project_role_background": "外戚勋贵稳定角色，可影响宫廷政治信任链条。",
    },
    "徐弘基": {
        "aliases": [],
        "office_history": ["魏国公", "南京勋贵体系核心"],
        "major_contributions": [
            "在南京地区维持传统勋贵秩序与资源分配。",
            "为南方政务与军事调度提供勋贵支持基础。",
        ],
        "related_events": ["南北军政资源分化", "明末南京防务讨论"],
        "project_role_background": "南方权力支点角色，影响南迁与地方协同事件。",
    },
    "周奎": {
        "aliases": [],
        "office_history": ["嘉定伯", "皇亲系统成员"],
        "major_contributions": [
            "以皇亲身份介入朝廷财政与捐输争议。",
            "甲申之变前后其行为成为舆论批评焦点。",
        ],
        "related_events": ["崇祯末财政征敛争议", "甲申之变"],
        "project_role_background": "低公信皇亲样本，适合触发“民意反噬”机制。",
    },
    "李国桢": {
        "aliases": ["李國楨"],
        "office_history": ["襄城伯", "京营提督（后期）"],
        "major_contributions": [
            "参与京营后期指挥体系运作。",
            "城防失守阶段的选择对政权合法性造成打击。",
        ],
        "related_events": ["京师防务危机", "甲申之变"],
        "project_role_background": "战时执行风险角色，可影响守城事件结果。",
    },
    "朱国弼": {
        "aliases": ["朱國弼"],
        "office_history": ["保国公", "勋贵集团成员"],
        "major_contributions": [
            "代表世袭勋贵在晚明政治中的持续存在。",
            "明清鼎革中的政治选择反映勋贵群体分裂。",
        ],
        "related_events": ["勋贵集团路线分化", "明清鼎革"],
        "project_role_background": "勋贵流动性样本，适合“忠诚衰减”系统建模。",
    },
    "袁崇焕": {
        "aliases": [],
        "office_history": ["辽东巡抚", "督师蓟辽（后期）"],
        "major_contributions": [
            "辽东防务核心将领，参与构建边防抗后金体系。",
            "己巳之变后被捕处置，成为崇祯朝军事政治转折点。",
        ],
        "related_events": ["宁远防务", "己巳之变", "袁崇焕案"],
        "project_role_background": "辽东战略核心角色，对边防强度与朝廷信任高度敏感。",
    },
    "孙承宗": {
        "aliases": [],
        "office_history": ["兵部尚书兼东阁大学士", "辽东督师（天启末）"],
        "major_contributions": [
            "在辽东防务与关宁体系建设中具有关键影响。",
            "晚期仍以资深将相身份参与边防讨论。",
        ],
        "related_events": ["关宁防线建设", "崇祯初辽东战略争论"],
        "project_role_background": "高威望老成将相，可提高辽东防务决策质量。",
    },
    "满桂": {
        "aliases": [],
        "office_history": ["总兵", "辽东边军将领"],
        "major_contributions": [
            "参与辽东边防作战，是明末重要武将之一。",
            "在己巳之变勤王作战中阵亡。",
        ],
        "related_events": ["辽东防务作战", "己巳之变"],
        "project_role_background": "高武力将领角色，可提升前线作战效能与军心。",
    },
    "赵率教": {
        "aliases": [],
        "office_history": ["总兵", "辽东边将"],
        "major_contributions": [
            "参与宁锦体系防务并承担勤王任务。",
            "在战时行动中阵亡，反映前线将领损耗压力。",
        ],
        "related_events": ["宁锦防线作战", "己巳之变勤王"],
        "project_role_background": "前线冲锋型武将，适合触发高风险战役事件。",
    },
    "毛文龙": {
        "aliases": [],
        "office_history": ["东江总兵", "皮岛体系主将"],
        "major_contributions": [
            "通过东江镇牵制后金，形成海陆边缘战略支点。",
            "其被处置引发边镇指挥权争议与连锁影响。",
        ],
        "related_events": ["东江镇经营", "袁崇焕斩毛文龙"],
        "project_role_background": "高争议边将角色，可显著影响辽东-海防联动。",
    },
    "祖大寿": {
        "aliases": [],
        "office_history": ["副总兵", "关宁军核心将领"],
        "major_contributions": [
            "长期活跃于关宁军体系，影响辽东战局走向。",
            "在关键战事中的立场变化对边防稳定冲击明显。",
        ],
        "related_events": ["大凌河之战", "松锦战事"],
        "project_role_background": "边军忠诚波动样本，适合“降附风险”机制。",
    },
    "何可纲": {
        "aliases": ["何可綱"],
        "office_history": ["副总兵", "关宁军将领"],
        "major_contributions": [
            "作为关宁军将领参与辽东防务与作战。",
            "在大凌河相关事件中殉难，成为忠义叙事对象。",
        ],
        "related_events": ["关宁军作战", "大凌河相关事件"],
        "project_role_background": "高忠诚边将角色，可提升将领群体士气。",
    },
}


def main() -> int:
    rows = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
    updated = 0
    for row in rows:
        name = row.get("name")
        payload = BATCH2_UPDATES.get(name)
        if not payload:
            continue
        row["aliases"] = payload.get("aliases", [])
        row["birth_year"] = None
        row["death_year"] = None
        row["office_history"] = payload.get("office_history", [])
        row["major_contributions"] = payload.get("major_contributions", [])
        row["related_events"] = payload.get("related_events", [])
        row["project_role_background"] = payload.get("project_role_background", "")
        row["sources"] = COMMON_SOURCES
        row["review"] = {
            "status": "in_review",
            "reviewer": "codex",
            "last_reviewed_on": REVIEW_DATE,
            "notes": "已补职责、贡献、事件与来源框架；待补《明史》具体卷次与逐条生卒年核定。",
        }
        updated += 1

    REVIEW_PATH.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Updated {updated} entries in {REVIEW_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
