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

BATCH3_UPDATES = {
    "吴三桂": {
        "aliases": [],
        "office_history": ["千总（早期）", "山海关总兵（后期）"],
        "major_contributions": [
            "崛起于辽东军系，后成为山海关关键将领。",
            "其政治军事选择对明清鼎革进程影响巨大。",
        ],
        "related_events": ["辽东军政变迁", "山海关局势转折"],
        "project_role_background": "高波动战略角色，显著影响边关开闭与政权结局分支。",
    },
    "曹文诏": {
        "aliases": ["曹文詔"],
        "office_history": ["参将", "中原剿匪主将"],
        "major_contributions": [
            "以剿寇作战能力著称，是明末前线悍将。",
            "在中原战场阵亡后对军心造成冲击。",
        ],
        "related_events": ["中原剿寇战事", "明军前线将领损耗"],
        "project_role_background": "高武力前线将领，可提升短期战绩但损耗风险高。",
    },
    "黄龙": {
        "aliases": [],
        "office_history": ["参将", "东江总兵（后续）"],
        "major_contributions": [
            "承接东江镇防务，维持海上牵制体系。",
            "在对后金作战中阵亡，反映东江系持续高压。",
        ],
        "related_events": ["东江镇防务延续", "辽东海防压力"],
        "project_role_background": "海防牵制型将领，影响边海联防稳定性。",
    },
    "刘兴祚": {
        "aliases": ["劉興祚"],
        "office_history": ["副将", "辽东边军联络角色"],
        "major_contributions": [
            "具备边疆双向接触经验，具有情报与联络价值。",
            "回归明方后不久战亡，体现边镇高风险环境。",
        ],
        "related_events": ["辽东边情渗透与反渗透", "边镇将领高损耗"],
        "project_role_background": "边情节点角色，可触发情报收益与暴露风险并存机制。",
    },
    "金国凤": {
        "aliases": ["金國鳳"],
        "office_history": ["参将", "辽东守备将领"],
        "major_contributions": [
            "参与松山、杏山等地防务。",
            "后续战事中阵亡，折射辽东防线人员损耗。",
        ],
        "related_events": ["松山杏山防务", "辽东守城消耗战"],
        "project_role_background": "守备型武将，偏向防线稳固与消耗管理。",
    },
    "尤世禄": {
        "aliases": ["尤世祿"],
        "office_history": ["宣府总兵", "勤王将领"],
        "major_contributions": [
            "承担北边重镇兵务并参与京畿勤王。",
            "在边防调度中影响京师外围防线稳态。",
        ],
        "related_events": ["宣府镇防务", "己巳之变勤王体系"],
        "project_role_background": "边镇机动角色，适合提升京畿外围应急能力。",
    },
    "杨鹤": {
        "aliases": ["楊鶴"],
        "office_history": ["右佥都御史", "三边总督（主抚路线）"],
        "major_contributions": [
            "在崇祯初主导抚剿策略中的“抚”向尝试。",
            "招抚失败后被问责，体现政策容错率低。",
        ],
        "related_events": ["崇祯初剿抚争论", "三边总督更替"],
        "project_role_background": "政策分歧关键角色，可触发“抚”路线收益与反噬。",
    },
    "杨嗣昌": {
        "aliases": ["楊嗣昌"],
        "office_history": ["兵部主事（早期）", "兵部尚书（后期）"],
        "major_contributions": [
            "提出系统性剿寇部署方案，主导中期军事策略。",
            "后期战局恶化导致其政治与心理压力集中爆发。",
        ],
        "related_events": ["四正六隅部署", "襄阳失守后政局震荡"],
        "project_role_background": "中期军事总策划角色，能显著影响全国战线压力分配。",
    },
    "卢象升": {
        "aliases": ["盧象升"],
        "office_history": ["大名知府（早期）", "总督天下勤王兵马（后期）"],
        "major_contributions": [
            "兼具文官治理与军事指挥能力。",
            "在大战中殉国，成为明末忠勇将臣代表。",
        ],
        "related_events": ["勤王军组织", "巨鹿战事"],
        "project_role_background": "高忠诚复合型将臣，可提高军纪与士气，但替代成本高。",
    },
    "陈奇瑜": {
        "aliases": ["陳奇瑜"],
        "office_history": ["陕西参议", "五省总督"],
        "major_contributions": [
            "曾在围剿战役中形成局部优势。",
            "因受降决策失当导致政治责任追究。",
        ],
        "related_events": ["车厢峡围剿", "剿抚政策反复"],
        "project_role_background": "成败波动型统帅角色，适合“战果-问责”联动机制。",
    },
    "孙传庭": {
        "aliases": ["孫傳庭"],
        "office_history": ["吏部主事（早期）", "中后期统兵将领"],
        "major_contributions": [
            "在剿寇战场屡建战功，是后期支柱将领之一。",
            "战败殉难后，明廷战略回旋空间进一步收缩。",
        ],
        "related_events": ["高迎祥被擒", "潼关战事"],
        "project_role_background": "后期核心将领角色，决定中原防线韧性上限。",
    },
    "洪承畴": {
        "aliases": ["洪承疇"],
        "office_history": ["陕西参政", "蓟辽总督（后期）"],
        "major_contributions": [
            "长期活跃于剿寇与边防一线，具备大规模统筹能力。",
            "关键战事后立场变化，成为明末政治象征事件。",
        ],
        "related_events": ["松锦战事", "明清鼎革中的将帅转向"],
        "project_role_background": "高能力高不确定性统帅，适合建模“忠诚-胜负”耦合。",
    },
    "左良玉": {
        "aliases": ["左良玉"],
        "office_history": ["参将（早期）", "后期拥兵大将"],
        "major_contributions": [
            "在中后期战场长期保持较强军事实力。",
            "后期军政关系紧张，形成尾大不掉风险。",
        ],
        "related_events": ["中原战场长期消耗", "南明初期兵权博弈"],
        "project_role_background": "强兵自重型角色，显著影响军纪与中央控制力。",
    },
    "贺人龙": {
        "aliases": ["賀人龍"],
        "office_history": ["参将", "中原剿寇将领"],
        "major_contributions": [
            "作战能力强但服从性与协同稳定性不足。",
            "后期被处置，体现军纪整肃代价。",
        ],
        "related_events": ["剿寇战场协同失灵", "将领整肃行动"],
        "project_role_background": "高战力低纪律样本，适合“军纪-战力权衡”事件。",
    },
    "曹变蛟": {
        "aliases": ["曹變蛟"],
        "office_history": ["千总", "中后期前线将领"],
        "major_contributions": [
            "在关键战事中承担突击任务，作战风格激进。",
            "最终被俘殉难，体现高风险突击战代价。",
        ],
        "related_events": ["松锦战事", "前线突击作战"],
        "project_role_background": "突击型将领，可短期提升战果但损失概率高。",
    },
    "傅宗龙": {
        "aliases": ["傅宗龍"],
        "office_history": ["巡抚", "三边总督（后期）"],
        "major_contributions": [
            "在困难局势下承接高压统筹任务。",
            "战败殉难，反映后期统帅资源衰减。",
        ],
        "related_events": ["三边战务重组", "后期战场失利"],
        "project_role_background": "危机接盘型将臣，适合“残局统筹”剧情分支。",
    },
    "丁启睿": {
        "aliases": ["丁啟睿"],
        "office_history": ["御史", "中期总督剿匪"],
        "major_contributions": [
            "参与中期剿寇部署并承担战场责任。",
            "重大失利后被问责，体现军政责任链。",
        ],
        "related_events": ["中期剿匪统筹", "朱仙镇相关失利"],
        "project_role_background": "中位统帅样本，适合验证问责机制对士气与忠诚影响。",
    },
    "熊文灿": {
        "aliases": ["熊文燦"],
        "office_history": ["福建巡抚", "总理剿匪（后期）"],
        "major_contributions": [
            "在招抚与地方军政协调中扮演重要角色。",
            "后因局势反复遭重罚，反映政策转向代价。",
        ],
        "related_events": ["招抚政策实践", "张献忠复叛后的追责"],
        "project_role_background": "招抚路线代表角色，适合“宽抚-反复”风险建模。",
    },
    "温体仁": {
        "aliases": ["溫體仁"],
        "office_history": ["礼部侍郎（早期）", "首辅（中期）"],
        "major_contributions": [
            "长期主导中枢运作，是崇祯朝中期权力核心。",
            "通过人事与议程控制深刻影响党争格局。",
        ],
        "related_events": ["崇祯中期内阁主导权", "党争与铨选控制"],
        "project_role_background": "中枢权术核心角色，可显著改变朝堂派系平衡。",
    },
    "王应熊": {
        "aliases": ["王應熊"],
        "office_history": ["礼部尚书", "入阁辅政"],
        "major_contributions": [
            "作为温体仁系重要成员参与中枢决策。",
            "体现中期内阁系谱与用人网络延伸。",
        ],
        "related_events": ["温体仁系上升", "崇祯中期阁局调整"],
        "project_role_background": "派系协同角色，可增强特定派系的政策执行能力。",
    },
}


def main() -> int:
    rows = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
    updated = 0
    for row in rows:
        name = row.get("name")
        payload = BATCH3_UPDATES.get(name)
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
