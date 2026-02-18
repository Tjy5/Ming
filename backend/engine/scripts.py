from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from models.game import GameState

from models.game import StructuredDecree
from models.enums import DecreeType, PersonnelAction, MinisterStatus


@dataclass
class ScriptChoice:
    label: str
    description: str
    decrees: list[StructuredDecree] = field(default_factory=list)
    loyalty_effects: list[tuple[str, int]] = field(default_factory=list)
    state_effects: dict[str, int] = field(default_factory=dict)


@dataclass
class ScriptEvent:
    script_id: str
    trigger_year: int
    trigger_month: int
    title: str
    rich_description: str
    choices: list[ScriptChoice]
    is_blocking: bool = False
    condition: Callable[[GameState], bool] | None = None


# ── Script Registry ─────────────────────────────────────

SCRIPT_REGISTRY: dict[str, ScriptEvent] = {}


def _register(evt: ScriptEvent) -> None:
    if not evt.script_id:
        raise ValueError("script_id must be non-empty")
    if evt.script_id in SCRIPT_REGISTRY:
        raise ValueError(f"duplicate script_id: {evt.script_id}")
    if not 1621 <= evt.trigger_year <= 1644:
        raise ValueError(f"trigger_year out of range: {evt.trigger_year}")
    if not 1 <= evt.trigger_month <= 12:
        raise ValueError(f"trigger_month out of range: {evt.trigger_month}")
    if not evt.choices:
        raise ValueError(f"script {evt.script_id} must have at least one choice")
    SCRIPT_REGISTRY[evt.script_id] = evt


def get_scripts_for_time(year: int, month: int) -> list[ScriptEvent]:
    return [
        e for e in SCRIPT_REGISTRY.values()
        if e.trigger_year == year and e.trigger_month == month
    ]


# ── Helper functions ────────────────────────────────────


def _faction_field(state, faction_name: str, field: str) -> int | None:
    f = next((f for f in state.factions if f.name == faction_name), None)
    return getattr(f, field) if f else None


def _region_field(state, region_name: str, field: str) -> int | None:
    r = next((r for r in state.regions if r.name == region_name), None)
    return getattr(r, field) if r else None


def _minister_active(state, name: str) -> bool:
    m = next((m for m in state.ministers if m.name == name), None)
    return m is not None and m.status == MinisterStatus.ACTIVE


# ── Phase 1: Progressive Monthly Scripts (1627/8 ~ 1628/8) ──

_register(ScriptEvent(
    script_id="chongzhen-accession-1627-08",
    trigger_year=1627,
    trigger_month=8,
    title="天启驾崩·信王即位",
    is_blocking=True,
    rich_description=(
        "**天启七年，八月。**\n\n"
        "八月二十二日，明熹宗朱由校驾崩于乾清宫，年仅二十三岁。"
        "遗诏传位于信王朱由检。八月二十四日，信王即皇帝位，"
        "是为崇祯帝。\n\n"
        "**朝局：** 魏忠贤仍以司礼监秉笔太监之权柄掌控朝政，"
        "阉党遍布朝堂内外，朝臣莫敢仰视。新君初立，根基未稳，"
        "魏忠贤于御前涕泣请辞以试探圣意。\n\n"
        "**边患：** 辽东后金虎视眈眈，宁远、锦州防线虽存，"
        "然边军粮饷拖欠日久。\n\n"
        "**民困：** 陕西连年大旱，饥民遍野，朝廷赈济杯水车薪。\n\n"
        "天下大势系于新君一念之间。当如何应对？"
    ),
    choices=[
        ScriptChoice(
            label="韬光养晦，稳住魏忠贤",
            description="暂且安抚魏忠贤，不动声色积蓄力量，徐图后计。",
            decrees=[],
        ),
        ScriptChoice(
            label="试探群臣态度",
            description="密召心腹大臣问计，探明朝中各派势力虚实。",
            decrees=[StructuredDecree(type=DecreeType.PERSONNEL, target="徐光启", sub_action=PersonnelAction.APPOINT)],
            loyalty_effects=[("徐光启", 10)],
        ),
        ScriptChoice(
            label="即刻清算阉党",
            description="乘魏忠贤请辞之机，雷厉风行将其罢黜。然根基未稳，恐生变故。",
            decrees=[StructuredDecree(type=DecreeType.PERSONNEL, target="魏忠贤", sub_action=PersonnelAction.DISMISS)],
            loyalty_effects=[("魏忠贤", -30)],
        ),
    ],
))

_register(ScriptEvent(
    script_id="court-ceremonies-1627-09",
    trigger_year=1627,
    trigger_month=9,
    title="追尊生母·册封皇后",
    is_blocking=False,
    rich_description=(
        "**天启七年，九月。**\n\n"
        "新君追尊生母刘氏为孝纯皇后，册封周氏为皇后。"
        "朝堂上下，礼仪大典次第举行。\n\n"
        "然典礼之际，暗流涌动。杨所修、陆澄源等朝臣试探性地"
        "上疏弹劾魏忠贤心腹崔呈秀，以窥测圣意。"
        "魏忠贤闻讯，面色微变，连日称病不出。\n\n"
        "朝中嗅觉敏锐之人已察觉风向将变。陛下当如何应对？"
    ),
    choices=[
        ScriptChoice(
            label="留中不发",
            description="对弹劾奏疏既不批准也不驳回，继续观望。",
            decrees=[],
        ),
        ScriptChoice(
            label="暗中鼓励",
            description="不公开表态，但私下示意言官继续上疏，壮大倒魏声势。",
            decrees=[StructuredDecree(type=DecreeType.PERSONNEL, target="崔呈秀", sub_action=PersonnelAction.DISMISS)],
        ),
    ],
))

_register(ScriptEvent(
    script_id="qian-jiazheng-impeachment-1627-10",
    trigger_year=1627,
    trigger_month=10,
    title="钱嘉征弹劾魏忠贤十大罪",
    is_blocking=False,
    rich_description=(
        "**天启七年，十月。**\n\n"
        "贡生钱嘉征上疏，历数魏忠贤十大罪状：\n"
        "并帝、蔑后、弄兵、无二祖列宗、克削藩封、"
        "无圣、滥爵、掩边功、罔利、好杀。\n\n"
        "奏疏传遍朝野，满朝震动。魏忠贤闻之'面如土色'，"
        "急入宫向新君涕泣请辞。圣上命内侍当面宣读弹章，"
        "魏忠贤'震恐丧魄'。\n\n"
        "是日，魏忠贤再请辞去司礼监秉笔太监之职。陛下当如何裁决？"
    ),
    choices=[
        ScriptChoice(
            label="准其辞职",
            description="顺水推舟，准许魏忠贤辞去秉笔太监之职，削其权柄。",
            decrees=[StructuredDecree(type=DecreeType.PERSONNEL, target="魏忠贤", sub_action=PersonnelAction.DISMISS)],
            loyalty_effects=[("魏忠贤", -20)],
        ),
        ScriptChoice(
            label="慰留观察",
            description="表面慰留，实则令其交出权力，以观后效。",
            decrees=[],
        ),
    ],
))

_register(ScriptEvent(
    script_id="wei-zhongxian-falls-1627-11",
    trigger_year=1627,
    trigger_month=11,
    title="魏忠贤伏诛·阉党崩溃",
    is_blocking=True,
    rich_description=(
        "**天启七年，十一月。**\n\n"
        "圣旨下：贬魏忠贤于凤阳守陵。魏忠贤离京南行，"
        "犹携从人四十余、大车四十辆、兵仗无数。\n\n"
        "朝臣纷纷上疏：阉贼虽去，犹拥重兵，恐有不测！"
        "圣上遂下令锦衣卫缉拿。魏忠贤行至阜城，闻讯后"
        "于十一月初六日缢死于旅舍。其党羽客氏亦被杖毙于浣衣局。\n\n"
        "阉党二十余年之祸，一朝崩溃。然朝局百废待兴，"
        "善后之策不可不慎。陛下将如何处置阉党余孽？"
    ),
    choices=[
        ScriptChoice(
            label="穷追猛打，彻底清算",
            description="将阉党余孽一网打尽，以儆效尤。朝政大振但恐株连过广。",
            decrees=[StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)],
            state_effects={"global.court_prestige": 10},
        ),
        ScriptChoice(
            label="适可而止，安定人心",
            description="首恶已除，余者从宽。安定朝局，避免人人自危。",
            decrees=[],
        ),
        ScriptChoice(
            label="分别处置，量刑有差",
            description="按罪行轻重分等定罪，首恶必办，胁从不问。",
            decrees=[StructuredDecree(type=DecreeType.PERSONNEL, target="魏忠贤", sub_action=PersonnelAction.DISMISS)],
        ),
    ],
))

_register(ScriptEvent(
    script_id="eunuch-party-purge-1627-12",
    trigger_year=1627,
    trigger_month=12,
    title="阉党清算·边镇欠饷",
    is_blocking=False,
    rich_description=(
        "**天启七年，腊月。**\n\n"
        "阉党清算如火如荼。魏忠贤'五虎''五彪'等党羽陆续被逮治。"
        "朝堂空出大量职位，各派争相推荐人选。\n\n"
        "然边事不容忽视。陕西固原镇欠饷已逾十月，"
        "兵丁怨声载道，哗变之势隐然可见。"
        "户部呈报：国库存银不足百万，入不敷出。\n\n"
        "清算与安边，孰先孰后？"
    ),
    choices=[
        ScriptChoice(
            label="继续清算，以儆效尤",
            description="阉党余毒未清，务必穷追到底。边事暂令地方筹措。",
            decrees=[StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)],
        ),
        ScriptChoice(
            label="拨银安边，稳住军心",
            description="先拨银补饷安定边军，阉党清算可徐图之。",
            decrees=[StructuredDecree(type=DecreeType.DISASTER_RELIEF, target="陕西")],
        ),
        ScriptChoice(
            label="双管齐下",
            description="一面继续清算，一面设法筹措军饷。但恐顾此失彼。",
            decrees=[StructuredDecree(type=DecreeType.TAX_INCREASE)],
        ),
    ],
))

_register(ScriptEvent(
    script_id="donglin-restoration-1628-01",
    trigger_year=1628,
    trigger_month=1,
    title="东林复起·禁内臣出禁门",
    is_blocking=False,
    rich_description=(
        "**崇祯元年，正月。**\n\n"
        "新年伊始，圣上下令戮魏忠贤、崔呈秀之尸，天下称快。"
        "又下诏禁止内臣出禁门干预政事，收回内臣监军之权。\n\n"
        "东林党人纷纷起复。朝堂上下，一扫阉党阴霾，"
        "群臣山呼万岁，誉新君为'中兴之主'。\n\n"
        "然东林党内部亦非铁板一块，门户之见渐生。"
        "陛下当如何驾驭这股新生力量？"
    ),
    choices=[
        ScriptChoice(
            label="大力起用东林贤臣",
            description="放手重用东林党人，以贤才充实朝堂。然恐形成一党独大之势。",
            decrees=[StructuredDecree(type=DecreeType.PERSONNEL, target="徐光启", sub_action=PersonnelAction.APPOINT)],
            loyalty_effects=[("徐光启", 15)],
        ),
        ScriptChoice(
            label="平衡各派，不偏不倚",
            description="兼用各派人才，维持朝堂平衡。然恐各方皆不满意。",
            decrees=[],
        ),
    ],
))

_register(ScriptEvent(
    script_id="rehabilitation-begins-1628-02",
    trigger_year=1628,
    trigger_month=2,
    title="起复冤臣·澄城余波",
    is_blocking=False,
    rich_description=(
        "**崇祯元年，二月。**\n\n"
        "圣上下诏为天启朝冤案平反，追赠被阉党迫害致死的忠臣。"
        "杨涟、左光斗、魏大中等人获追谥，天下忠义之士为之涕零。\n\n"
        "然陕西传来急报：澄城县饥民王二聚众数百，"
        "杀知县张斗耀，虽已被镇压，但余波未平。"
        "此乃天启以来民变之延续，饥荒之祸愈演愈烈。\n\n"
        "朝廷何以应对？"
    ),
    choices=[
        ScriptChoice(
            label="加大赈灾力度",
            description="拨银赈济陕西灾民，以防民变再起。",
            decrees=[StructuredDecree(type=DecreeType.DISASTER_RELIEF, target="陕西")],
        ),
        ScriptChoice(
            label="严惩乱民以儆效尤",
            description="严厉镇压，杀一儆百。虽可震慑一时，但恐激化矛盾。",
            decrees=[StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)],
        ),
        ScriptChoice(
            label="责令地方自行处置",
            description="朝廷已焦头烂额，令地方官自行弹压赈济。",
            decrees=[],
            state_effects={"region.陕西.stability": -5},
        ),
    ],
))

_register(ScriptEvent(
    script_id="tianqi-burial-1628-03",
    trigger_year=1628,
    trigger_month=3,
    title="葬熹宗德陵·阉党阁臣致仕",
    is_blocking=False,
    rich_description=(
        "**崇祯元年，三月。**\n\n"
        "葬熹宗于德陵，国丧礼毕。阉党阁臣施凤来、张瑞图等"
        "相继致仕去位，朝堂渐归清明。\n\n"
        "圣上追赠天启朝被迫害的忠臣，录用遗孤。"
        "然新朝初立，百事待举。吏部奏称：各部缺员甚众，"
        "急需铨选补任。\n\n"
        "如何充实朝堂？"
    ),
    choices=[
        ScriptChoice(
            label="大举选贤任能",
            description="广开才路，遍选天下英才充实朝堂。",
            decrees=[StructuredDecree(type=DecreeType.PERSONNEL, target="徐光启", sub_action=PersonnelAction.APPOINT)],
        ),
        ScriptChoice(
            label="稳步补缺，量才录用",
            description="按部就班，逐步补充各部缺员。",
            decrees=[],
        ),
    ],
))

_register(ScriptEvent(
    script_id="yuan-chonghuan-appointed-1628-04",
    trigger_year=1628,
    trigger_month=4,
    title="袁崇焕督师蓟辽",
    is_blocking=False,
    rich_description=(
        "**崇祯元年，四月。**\n\n"
        "圣上召袁崇焕入京，擢为兵部尚书兼右副都御史，"
        "督师蓟辽，赐尚方剑。袁崇焕慷慨陈词，誓言'五年平辽'。\n\n"
        "然辽东军务浩繁，军需甚巨。户部呈报：辽饷岁支四百万两，"
        "已占国帑半数有余。\n\n"
        "与此同时，陕西饥荒持续扩大。延安、庆阳诸府，"
        "斗米价银一两有余，饥民成群结队南下就食。\n\n"
        "辽饷与赈灾，如何兼顾？"
    ),
    choices=[
        ScriptChoice(
            label="优先保障辽饷",
            description="边防为重，全力保障袁崇焕军需。陕西赈灾暂缓。",
            decrees=[StructuredDecree(type=DecreeType.RECRUIT_TROOPS)],
        ),
        ScriptChoice(
            label="拨银赈灾陕西",
            description="民为邦本，先安内后攘外。但辽东军需恐捉襟见肘。",
            decrees=[StructuredDecree(type=DecreeType.DISASTER_RELIEF, target="陕西")],
        ),
        ScriptChoice(
            label="加征赋税两头兼顾",
            description="加征赋税以同时满足军需和赈灾。然恐加重百姓负担。",
            decrees=[StructuredDecree(type=DecreeType.TAX_INCREASE)],
        ),
    ],
))

_register(ScriptEvent(
    script_id="farmer-uprising-erupts-1628-05",
    trigger_year=1628,
    trigger_month=5,
    title="焚《三朝要典》·农民大起义前夜",
    is_blocking=True,
    rich_description=(
        "**崇祯元年，五月。**\n\n"
        "圣上下令焚毁阉党编纂的《三朝要典》，天下称快。\n\n"
        "然陕西巡按马懋才上《备陈大饥疏》，字字血泪：\n"
        "'臣自去秋至今，所见所闻，饿殍遍地，炊烟断绝。"
        "百姓食树皮、掘草根以求苟活，甚有易子而食者。"
        "延安一府，死者过半。流亡四方者，不知凡几。'\n\n"
        "府谷一带，王嘉胤、王左挂等人聚饥民数千，"
        "揭竿而起。明末农民大起义之序幕，已然拉开。\n\n"
        "朝廷当如何应对这场滔天巨变？"
    ),
    choices=[
        ScriptChoice(
            label="急调兵马镇压",
            description="调遣延绥镇兵力围剿，力图将起义扑灭于萌芽。",
            decrees=[StructuredDecree(type=DecreeType.RECRUIT_TROOPS)],
            state_effects={"global.treasury": -15},
        ),
        ScriptChoice(
            label="大举赈灾安民",
            description="拨重金赈济灾民，釜底抽薪，使饥民无需从贼。",
            decrees=[StructuredDecree(type=DecreeType.DISASTER_RELIEF, target="陕西")],
        ),
        ScriptChoice(
            label="剿抚并用",
            description="一面调兵弹压，一面开仓赈济。但恐国库难以支撑两线开支。",
            decrees=[StructuredDecree(type=DecreeType.TAX_INCREASE)],
        ),
    ],
))

_register(ScriptEvent(
    script_id="famine-escalates-1628-06",
    trigger_year=1628,
    trigger_month=6,
    title="饥荒蔓延·流民四起",
    is_blocking=False,
    rich_description=(
        "**崇祯元年，六月。**\n\n"
        "陕西、山西饥荒持续加剧。自延安至平凉、庆阳，"
        "赤地千里，饿殍遍野。大批饥民涌入山西、河南就食。\n\n"
        "各地奏报纷至沓来：\n"
        "· 王嘉胤部已聚众万余，盘踞府谷、神木一带\n"
        "· 王左挂、苗美等人亦各拥数千之众\n"
        "· 流民所过之处，仓廒空竭，官军莫敢阻挡\n\n"
        "地方官吏纷纷请旨增兵增饷，然户部已捉襟见肘。"
    ),
    choices=[
        ScriptChoice(
            label="增拨赈灾银两",
            description="再拨国库银两赈济灾区，缓解饥民之急。",
            decrees=[StructuredDecree(type=DecreeType.DISASTER_RELIEF, target="陕西")],
        ),
        ScriptChoice(
            label="调兵进剿",
            description="增调兵马围剿起义军，以武力恢复秩序。",
            decrees=[StructuredDecree(type=DecreeType.RECRUIT_TROOPS)],
        ),
        ScriptChoice(
            label="静观其变",
            description="朝廷无力兼顾，暂且令地方自行筹措。",
            decrees=[],
            state_effects={"region.陕西.stability": -8, "region.中原.stability": -5},
        ),
    ],
))

_register(ScriptEvent(
    script_id="ningyuan-mutiny-1628-07",
    trigger_year=1628,
    trigger_month=7,
    title="平台召对·宁远兵变",
    is_blocking=True,
    rich_description=(
        "**崇祯元年，七月。**\n\n"
        "圣上于平台召见袁崇焕，君臣对策。袁崇焕豪言'五年平辽'，"
        "圣上大悦，许以便宜行事之权。\n\n"
        "然七月二十五日，辽东宁远驻军因欠饷四月有余，"
        "哗变夺门，绑缚巡抚毕自肃。毕自肃不堪其辱，愤而自尽。\n\n"
        "消息传至京师，朝野震惊。边军之乱，若不速平，"
        "后金闻讯必趁虚而入。\n\n"
        "与此同时，高迎祥等义军活跃于陕北，声势日壮。"
        "内忧外患交织，陛下当如何决断？"
    ),
    choices=[
        ScriptChoice(
            label="急拨军饷平息兵变",
            description="不惜代价拨银补饷，先稳住辽东防线。",
            decrees=[StructuredDecree(type=DecreeType.TAX_INCREASE)],
            state_effects={"global.military_morale": 5},
        ),
        ScriptChoice(
            label="严惩哗变首恶",
            description="以军法惩处带头闹事之人，以儆效尤。然恐激化军心。",
            decrees=[StructuredDecree(type=DecreeType.HARSH_PUNISHMENT)],
            state_effects={"faction.边将势力.satisfaction": -10},
        ),
        ScriptChoice(
            label="令袁崇焕自行处置",
            description="已授袁崇焕便宜行事之权，令其自行平乱。",
            decrees=[],
            state_effects={"region.辽东.stability": -10},
        ),
    ],
))

_register(ScriptEvent(
    script_id="year-end-assessment-1628-08",
    trigger_year=1628,
    trigger_month=8,
    title="周年回顾·天下大势",
    is_blocking=True,
    rich_description=(
        "**崇祯元年，八月。**\n\n"
        "即位整整一年。圣上日于文华殿视朝议政，勤勉不辍，"
        "群臣莫不感佩。\n\n"
        "然天下之势，忧多喜少：\n"
        "· 全陕大饥，赤地千里，起义军已聚众数万\n"
        "· 辽东虽有袁崇焕坐镇，然军饷时有不继\n"
        "· 后金持续绥服漠南蒙古各部，为大举入塞做准备\n"
        "· 国库空虚，入不敷出，加征辽饷已令百姓苦不堪言\n\n"
        "一年之计，在于此时。来年方略，当如何定夺？"
    ),
    choices=[
        ScriptChoice(
            label="攘外为先",
            description="集中财力军力于辽东，优先应对后金威胁。",
            decrees=[StructuredDecree(type=DecreeType.RECRUIT_TROOPS)],
            state_effects={"global.military_morale": 5, "global.treasury": -20},
        ),
        ScriptChoice(
            label="安内为先",
            description="先平陕西民变、赈济灾民，稳固后方再图辽东。",
            decrees=[StructuredDecree(type=DecreeType.DISASTER_RELIEF, target="陕西")],
        ),
        ScriptChoice(
            label="内外兼顾",
            description="加征赋税，试图两线兼顾。然恐百姓不堪重负。",
            decrees=[StructuredDecree(type=DecreeType.TAX_INCREASE)],
        ),
    ],
))


# ── Phase 2: Extended Historical Scripts (1629-1631) ───

_register(ScriptEvent(
    script_id="jisi-invasion",
    trigger_year=1629,
    trigger_month=10,
    title="己巳之变·皇太极入寇",
    is_blocking=True,
    rich_description=(
        "**崇祯二年，十月。**\n\n"
        "后金大汗皇太极率精骑绕道蒙古，突破长城隘口，"
        "直逼京畿。蓟镇烽火昼夜不绝，京师震动。\n\n"
        "廷臣争论不休：或请速战，或请和议，或请坚壁清野。"
        "皇城内外人心惶惶，仓卒调度稍有失当，便可能酿成大祸。\n\n"
        "天子当如何应对这场突如其来的危机？"
    ),
    choices=[
        ScriptChoice(
            label="急召天下勤王",
            description="集中各路兵马勤王，以战止战。辽东、京畿防线将受冲击。",
            decrees=[StructuredDecree(type=DecreeType.RECRUIT_TROOPS)],
            state_effects={
                "region.辽东.stability": -20,
                "region.京畿.stability": -20,
                "global.military_morale": 10,
            },
        ),
        ScriptChoice(
            label="固守京城待援",
            description="紧闭城门，坚壁清野，等待各路援军。然京畿百姓将遭涂炭。",
            decrees=[],
            state_effects={
                "region.京畿.stability": -15,
                "global.court_prestige": -10,
            },
        ),
        ScriptChoice(
            label="命袁崇焕回援",
            description="急令袁崇焕率辽东精锐回师勤王，试图以外交拖延后金攻势。",
            decrees=[StructuredDecree(type=DecreeType.DIPLOMACY, target="后金")],
        ),
    ],
))

_register(ScriptEvent(
    script_id="yuan-chonghuan-arrest",
    trigger_year=1629,
    trigger_month=12,
    title="袁崇焕下狱",
    is_blocking=True,
    condition=lambda s: "jisi-invasion" in s.resolved_script_ids,
    rich_description=(
        "**崇祯二年，十二月。**\n\n"
        "京师解围后，朝野对袁崇焕毁誉并起。"
        "有弹劾其通敌卖国者，有言其擅杀毛文龙、纵敌入关者，"
        "亦有力保其忠勇者。风闻交织，真伪难辨。\n\n"
        "若轻断重臣，恐伤军心；若久拖不决，又损朝廷威信。"
        "圣裁所向，将决定边防命脉。"
    ),
    choices=[
        ScriptChoice(
            label="逮捕袁崇焕",
            description="先行收系问罪，以平京师汹汹舆情。边将势力恐大为震动。",
            decrees=[StructuredDecree(
                type=DecreeType.PERSONNEL,
                target="袁崇焕",
                sub_action=PersonnelAction.DISMISS,
            )],
            loyalty_effects=[("袁崇焕", -50)],
            state_effects={
                "faction.边将势力.satisfaction": -25,
                "faction.边将势力.rebellion_risk": 20,
            },
        ),
        ScriptChoice(
            label="力排众议，保袁崇焕",
            description="顶住压力为袁崇焕辩护。阉党残余与勋贵集团恐更加不满。",
            decrees=[],
            loyalty_effects=[("袁崇焕", 20)],
            state_effects={
                "faction.阉党残余.satisfaction": -15,
                "faction.勋贵集团.satisfaction": -15,
                "global.court_prestige": -10,
            },
        ),
    ],
))

_register(ScriptEvent(
    script_id="li-zicheng-joins",
    trigger_year=1630,
    trigger_month=3,
    title="陕西大起义·李自成从军",
    is_blocking=False,
    condition=lambda s: (_v := _region_field(s, "陕西", "stability")) is not None and _v < 30,
    rich_description=(
        "**崇祯三年，三月。**\n\n"
        "陕西驿递裁汰，失业驿卒与饥民并起。"
        "米脂人李自成弃役从伍，投身闯军，渐露锋芒。\n\n"
        "地方官奏称：若任其流聚，陕北山川易守难攻，"
        "势必尾大不掉。流寇之势已非一县一府所能弹压。"
    ),
    choices=[
        ScriptChoice(
            label="重兵围剿",
            description="调集重兵围剿，力图将流寇扼杀于萌芽。然耗费甚巨。",
            decrees=[StructuredDecree(type=DecreeType.RECRUIT_TROOPS)],
            state_effects={
                "region.陕西.stability": 10,
                "global.treasury": -20,
            },
        ),
        ScriptChoice(
            label="分化瓦解",
            description="与蒙古通好以减少多线压力，腾出手来对付流寇。",
            decrees=[StructuredDecree(type=DecreeType.DIPLOMACY, target="蒙古")],
        ),
        ScriptChoice(
            label="置之不理",
            description="朝廷无暇西顾，任由地方自行应对。陕西与中原恐将动荡加剧。",
            decrees=[],
            state_effects={
                "region.陕西.stability": -15,
                "region.中原.stability": -10,
            },
        ),
    ],
))

_register(ScriptEvent(
    script_id="sun-chengzong-recovery",
    trigger_year=1630,
    trigger_month=5,
    title="孙承宗收复遵化四城",
    is_blocking=False,
    condition=lambda s: _minister_active(s, "孙承宗") and s.military_supply > 40,
    rich_description=(
        "**崇祯三年，五月。**\n\n"
        "老将孙承宗率军反攻，连克遵化、永平、迁安、滦州四城，"
        "后金残部退出关内。辽东军民士气大振。\n\n"
        "然追击深入恐有伏兵之险，见好就收亦可巩固战果。"
        "陛下当如何决断？"
    ),
    choices=[
        ScriptChoice(
            label="乘胜追击",
            description="趁后金立足未稳，挥师追击，力图扩大战果。然耗费军资甚巨。",
            decrees=[StructuredDecree(type=DecreeType.RECRUIT_TROOPS)],
            state_effects={
                "region.辽东.stability": 15,
                "global.military_morale": 10,
                "global.treasury": -25,
            },
        ),
        ScriptChoice(
            label="见好就收、巩固防线",
            description="收复四城已是大功，当务之急是巩固防线、休整军队。",
            decrees=[],
            state_effects={
                "region.辽东.stability": 10,
                "global.court_prestige": 5,
            },
        ),
    ],
))

_register(ScriptEvent(
    script_id="dalinghe-prelude",
    trigger_year=1631,
    trigger_month=8,
    title="大凌河之围前奏",
    is_blocking=False,
    condition=lambda s: (_v := _region_field(s, "辽东", "stability")) is not None and _v < 40,
    rich_description=(
        "**崇祯四年，八月。**\n\n"
        "后金蓄势准备围攻大凌河，辽东局势再度紧张。"
        "前线请示是增援固守还是收缩防线。\n\n"
        "辽东诸堡互为犄角，一处失守便可能牵动全局。"
        "兵部连夜会同督抚上奏，请陛下速定方略。"
    ),
    choices=[
        ScriptChoice(
            label="增援大凌河",
            description="增兵固守大凌河，消耗军备但可稳住辽东防线。",
            decrees=[StructuredDecree(type=DecreeType.RECRUIT_TROOPS)],
            state_effects={
                "global.military_supply": -15,
                "region.辽东.stability": 5,
            },
        ),
        ScriptChoice(
            label="收缩防线",
            description="放弃外围据点，收缩兵力于核心堡寨。辽东稳定将受损但可节约军费。",
            decrees=[StructuredDecree(type=DecreeType.DISBAND_TROOPS)],
            state_effects={"region.辽东.stability": -10},
        ),
    ],
))
