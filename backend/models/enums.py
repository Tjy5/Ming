from enum import Enum


class DecreeType(str, Enum):
    TAX_INCREASE = "tax_increase"
    TAX_DECREASE = "tax_decrease"
    RECRUIT_TROOPS = "recruit_troops"
    DISBAND_TROOPS = "disband_troops"
    PERSONNEL = "personnel"
    DIPLOMACY = "diplomacy"
    DISASTER_RELIEF = "disaster_relief"
    HARSH_PUNISHMENT = "harsh_punishment"


class RegionControl(str, Enum):
    COURT = "朝廷"
    UNSTABLE = "失控"
    FALLEN = "沦陷"


class RegionThreat(str, Enum):
    NONE = "none"
    HOUJIN = "后金"
    REBELLION = "民变"
    TUSI = "土司"
    PIRATE = "海盗"


class TaxContribution(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PersonnelAction(str, Enum):
    APPOINT = "appoint"
    DISMISS = "dismiss"
    EXECUTE = "execute"


class DiplomacyTarget(str, Enum):
    HOUJIN = "后金"
    MONGOL = "蒙古"
    JOSEON = "朝鲜"


class EventUrgency(str, Enum):
    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"


class MinisterStatus(str, Enum):
    ACTIVE = "active"
    IDLE = "idle"
    REMOVED = "removed"


class MemorialStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"
