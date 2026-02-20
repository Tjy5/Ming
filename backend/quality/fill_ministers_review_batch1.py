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

BATCH1_UPDATES = {
    "韩爌": {
        "aliases": ["韓爌"],
        "office_history": ["礼部尚书兼东阁大学士", "内阁辅臣（崇祯初）"],
        "major_contributions": [
            "崇祯即位后起复入阁，参与倒魏善后与中枢重整。",
            "以内阁辅臣身份参与早期政务协调。",
        ],
        "related_events": ["崇祯初阉党清算", "东林复起"],
        "project_role_background": "前期中枢稳定角色，影响朝堂秩序与东林党路线。",
    },
    "钱谦益": {
        "aliases": ["錢謙益"],
        "birth_year": 1582,
        "death_year": 1664,
        "office_history": ["礼部侍郎", "南明弘光朝礼部尚书（后期）"],
        "major_contributions": [
            "明末文坛与士林核心人物，对士人网络影响显著。",
            "南明时期继续参与礼部政务。",
        ],
        "related_events": ["崇祯初东林复起", "南明弘光政权建立"],
        "project_role_background": "偏文治与士林动员角色，可提高文化声望并放大党争效应。",
    },
    "钱龙锡": {
        "aliases": ["錢龍錫"],
        "office_history": ["吏部侍郎", "入阁辅政（崇祯初）"],
        "major_contributions": [
            "崇祯初参与内阁辅政，涉及早期人事与议政。",
            "在袁崇焕案中受牵连，体现朝局连带风险。",
        ],
        "related_events": ["崇祯初内阁重组", "袁崇焕案"],
        "project_role_background": "中枢协同型角色，适合承接人事与议政事件链。",
    },
    "成基命": {
        "aliases": [],
        "office_history": ["礼部侍郎", "入阁辅政（崇祯初）"],
        "major_contributions": [
            "崇祯初年入阁参与政务，风格偏宽厚持重。",
            "在重大司法争议中倾向主张宽减。",
        ],
        "related_events": ["崇祯初阁臣调整", "明末大狱争议"],
        "project_role_background": "温和调和型角色，可用于缓和极端政令副作用。",
    },
    "文震孟": {
        "aliases": [],
        "birth_year": 1574,
        "death_year": 1636,
        "office_history": ["翰林编修", "状元出身"],
        "major_contributions": [
            "以直谏著称，曾因触忤权阉受打击。",
            "崇祯初复官后成为士人清议代表之一。",
        ],
        "related_events": ["天启朝阉党政治", "崇祯初东林复起"],
        "project_role_background": "高道德声望谏诤角色，可强化“清议”路线。",
    },
    "黄道周": {
        "aliases": [],
        "birth_year": 1585,
        "death_year": 1646,
        "office_history": ["翰林编修", "后期南明重臣"],
        "major_contributions": [
            "以理学与直谏著称，多次因言事受挫。",
            "南明时期继续抗清并殉国。",
        ],
        "related_events": ["崇祯朝言官政治", "南明抗清"],
        "project_role_background": "高忠诚高原则角色，利于提升道统与士气。",
    },
    "刘宗周": {
        "aliases": ["劉宗周"],
        "birth_year": 1578,
        "death_year": 1645,
        "office_history": ["顺天府尹", "明末著名谏臣"],
        "major_contributions": [
            "以清正与讲学并重著称，长期参与言路监督。",
            "多次被贬复起，反映明末政治震荡。",
        ],
        "related_events": ["崇祯朝党争", "甲申前后士人殉节"],
        "project_role_background": "清流标杆角色，对权术型政策容忍度低。",
    },
    "倪元璐": {
        "aliases": [],
        "birth_year": 1593,
        "death_year": 1644,
        "office_history": ["翰林编修", "户部尚书（崇祯末）"],
        "major_contributions": [
            "兼具文名与政务能力，晚期承担财政与中枢职责。",
            "甲申之变中殉国。",
        ],
        "related_events": ["崇祯末财政危机", "甲申之变"],
        "project_role_background": "文官财政线核心角色，可承接危机时期忠诚抉择。",
    },
    "范景文": {
        "aliases": ["範景文"],
        "birth_year": 1581,
        "death_year": 1644,
        "office_history": ["河南巡抚", "入阁（崇祯末）"],
        "major_contributions": [
            "历任地方与中枢职位，治理风格偏务实。",
            "甲申之变时殉国。",
        ],
        "related_events": ["崇祯末中枢更迭", "甲申之变"],
        "project_role_background": "地方-中枢转换型角色，适合作为危机期执行官。",
    },
    "史可法": {
        "aliases": [],
        "birth_year": 1601,
        "death_year": 1645,
        "office_history": ["户部主事（早期）", "后期督师江北"],
        "major_contributions": [
            "明末重要军事政治人物，后期组织江北防务。",
            "扬州失守后殉国，成为抗清象征。",
        ],
        "related_events": ["崇祯末北方战局恶化", "南明弘光政权与扬州之役"],
        "project_role_background": "高忠诚军事政治核心，可显著影响后期战局与士气。",
    },
    "姜曰广": {
        "aliases": ["姜曰廣"],
        "office_history": ["翰林侍读", "南明弘光朝礼部尚书"],
        "major_contributions": [
            "崇祯朝以翰林身份参与中枢文政。",
            "南明时期继续任礼部要职。",
        ],
        "related_events": ["崇祯朝阁局变化", "南明弘光政务"],
        "project_role_background": "文官制度延续角色，可连接明末与南明阶段叙事。",
    },
    "高弘图": {
        "aliases": ["高弘圖"],
        "birth_year": 1583,
        "death_year": 1645,
        "office_history": ["光禄少卿", "南明弘光朝首辅"],
        "major_contributions": [
            "明末至南明过渡期的重要文臣。",
            "在南明政权中担任首辅参与中枢决策。",
        ],
        "related_events": ["甲申后政权重组", "南明弘光朝内阁运作"],
        "project_role_background": "过渡政权核心文臣，可影响南迁后政权稳定度。",
    },
    "马世奇": {
        "aliases": [],
        "birth_year": 1605,
        "death_year": 1644,
        "office_history": ["翰林编修", "明末殉国士臣"],
        "major_contributions": [
            "以翰林出身进入中枢文臣系统。",
            "甲申之变殉国。",
        ],
        "related_events": ["崇祯末中枢压力", "甲申之变"],
        "project_role_background": "高忠诚文臣角色，适合作为“城破殉节”分支触发点。",
    },
    "吴甡": {
        "aliases": [],
        "office_history": ["御史", "崇祯中期入阁（后去职）"],
        "major_contributions": [
            "以言官身份参与政策辩论，涉及剿抚路线讨论。",
            "中期入阁后又因政争退出中枢。",
        ],
        "related_events": ["崇祯中期剿抚争论", "内阁更替"],
        "project_role_background": "政策争论型角色，可牵引“剿”与“抚”路径分歧。",
    },
    "瞿式耜": {
        "aliases": [],
        "birth_year": 1590,
        "death_year": 1650,
        "office_history": ["吏科给事中", "南明永历朝重臣"],
        "major_contributions": [
            "明末言官体系成员，参与朝政监察。",
            "南明永历政权中坚持抗清并殉国。",
        ],
        "related_events": ["崇祯末言路政治", "南明永历抗清"],
        "project_role_background": "南明抗清线关键角色，利于构建后期忠义叙事。",
    },
    "魏忠贤": {
        "aliases": ["魏忠賢"],
        "birth_year": 1568,
        "death_year": 1627,
        "office_history": ["司礼监秉笔太监", "内廷权力核心"],
        "major_contributions": [
            "天启朝主导内廷权力网络，深刻影响官僚任免。",
            "崇祯初被清算，是明末政治转折关键节点。",
        ],
        "related_events": ["阉党专权", "崇祯初清算阉党"],
        "project_role_background": "高风险高影响反派核心，决定开局政治难度与朝局走向。",
    },
    "崔呈秀": {
        "aliases": [],
        "office_history": ["兵部尚书", "阉党骨干"],
        "major_contributions": [
            "作为阉党核心成员参与中枢权力运作。",
            "崇祯清算阉党时自尽。",
        ],
        "related_events": ["阉党专政", "崇祯初阉党清算"],
        "project_role_background": "阉党网络关键节点，影响兵部与党争事件触发概率。",
    },
    "田尔耕": {
        "aliases": ["田爾耕"],
        "office_history": ["锦衣卫指挥使"],
        "major_contributions": [
            "掌锦衣卫期间参与高压政治与案件办理。",
            "崇祯初因阉党案被处置。",
        ],
        "related_events": ["天启末诏狱政治", "崇祯初逆案清算"],
        "project_role_background": "强制执法型角色，可改变朝臣恐惧与忠诚结构。",
    },
    "许显纯": {
        "aliases": ["許顯純"],
        "office_history": ["北镇抚司"],
        "major_contributions": [
            "以酷吏形象参与阉党时期政治迫害。",
            "崇祯初被处置，成为清算阉党的标志对象。",
        ],
        "related_events": ["东林党案与诏狱", "崇祯初阉党清算"],
        "project_role_background": "高压统治代表角色，可作为“严刑路线”副作用参照。",
    },
    "冯铨": {
        "aliases": ["馮銓"],
        "birth_year": 1595,
        "death_year": 1672,
        "office_history": ["文渊阁大学士", "明末降清后复起"],
        "major_contributions": [
            "早年入阁并卷入阉党政治网络。",
            "明清鼎革中再度出仕，体现士大夫政治选择分化。",
        ],
        "related_events": ["崇祯初逆案处理", "明清鼎革中的仕宦转向"],
        "project_role_background": "立场可变型高层文臣，适合建模“忠节-现实”抉择分支。",
    },
}


def main() -> int:
    rows = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
    updated = 0
    for row in rows:
        name = row.get("name")
        payload = BATCH1_UPDATES.get(name)
        if not payload:
            continue
        row["aliases"] = payload.get("aliases", [])
        row["birth_year"] = payload.get("birth_year")
        row["death_year"] = payload.get("death_year")
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
