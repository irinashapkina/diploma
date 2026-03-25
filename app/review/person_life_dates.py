from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class PersonLifeDatesFormat (str ,Enum ):
    living_birth_only ="living_birth_only"
    open_interval ="open_interval"
    closed_interval ="closed_interval"
    death_only ="death_only"
    approx_or_historical ="approx_or_historical"


class PersonLifeStatus (str ,Enum ):
    living ="living"
    deceased ="deceased"
    unknown ="unknown"


@dataclass (slots =True ,frozen =True )
class PersonLifeDatesStyle :
    bracketed :bool
    dash :str |None =None
    birth_prefix :str |None =None
    death_prefix :str |None =None
    space_after_dash :bool =False


@dataclass (slots =True ,frozen =True )
class PersonLifeDatesMention :
    person_name :str
    matched_text :str
    start :int
    end :int
    birth_year :int |None
    death_year :int |None
    format_type :PersonLifeDatesFormat
    raw_style :PersonLifeDatesStyle
    confidence :float
    text_status :PersonLifeStatus


PARTICLE_RE =r"(?:de|da|del|di|van|von|der|ден|де|фон|аль)"
NAME_TOKEN_RE =rf"(?:[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё'’.-]+|{PARTICLE_RE})"
NAME_RE =re .compile (
rf"(?P<person>(?:{NAME_TOKEN_RE})(?:\s+{NAME_TOKEN_RE}){{0,5}})\s*(?P<dates>\((?P<inside>[^()\n]{{2,40}})\))"
)
BIRTH_PREFIX_RE =re .compile (r"^(?P<prefix>р\.|род\.|born|b\.)\s*(?P<birth>\d{3,4})\s*$",re .IGNORECASE )
DEATH_PREFIX_RE =re .compile (r"^(?P<prefix>ум\.|сконч\.|died|d\.)\s*(?P<death>\d{3,4})\s*$",re .IGNORECASE )
OPEN_INTERVAL_RE =re .compile (r"^(?P<birth>\d{3,4})\s*(?P<dash>[—–-])\s*$")
CLOSED_INTERVAL_RE =re .compile (r"^(?P<birth>\d{3,4})\s*(?P<dash>[—–-])\s*(?P<death>\d{3,4})\s*$")
HISTORICAL_RE =re .compile (r"(до\s+н\.\s*э\.|bc|bce)",re .IGNORECASE )
SUSPECT_NAME_RE =re .compile (r"^[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё]+$")


def extract_person_life_dates (text :str )->list [PersonLifeDatesMention ]:
    mentions :list [PersonLifeDatesMention ]=[]
    for match in NAME_RE .finditer (text ):
        person_name =match .group ("person").strip ()
        dates_text =match .group ("dates")
        parsed =_parse_dates_payload (match .group ("inside"))
        if parsed is None :
            continue
        confidence =0.87 if len (person_name .split ())>=2 else 0.7
        if SUSPECT_NAME_RE .match (person_name ):
            confidence =min (confidence ,0.72 )
        mentions .append (
        PersonLifeDatesMention (
        person_name =person_name ,
        matched_text =dates_text ,
        start =match .start ("dates"),
        end =match .end ("dates"),
        birth_year =parsed ["birth_year"],
        death_year =parsed ["death_year"],
        format_type =parsed ["format_type"],
        raw_style =parsed ["raw_style"],
        confidence =confidence ,
        text_status =parsed ["text_status"],
        )
        )
    return mentions


def render_person_life_dates (
mention :PersonLifeDatesMention ,
birth_year :int |None ,
death_year :int |None ,
is_living :bool |None ,
)->str |None :
    if birth_year is None :
        return None
    style =mention .raw_style
    if mention .format_type ==PersonLifeDatesFormat .approx_or_historical :
        return None
    if is_living is None :
        return None
    if is_living :
        prefix =style .birth_prefix or _infer_living_birth_prefix (mention )
        return f"({prefix} {birth_year})"
    if death_year is None :
        return None
    dash =style .dash or "–"
    space = " "if style .space_after_dash else ""
    return f"({birth_year}{dash}{space}{death_year})"


def _parse_dates_payload (inside :str )->dict |None :
    cleaned =inside .strip ()
    if HISTORICAL_RE .search (cleaned ):
        years =[int (piece )for piece in re .findall (r"\d{3,4}",cleaned )[:2 ]]
        return {
        "birth_year":years [0 ]if years else None,
        "death_year":years [1 ]if len (years )>1 else None,
        "format_type":PersonLifeDatesFormat .approx_or_historical ,
        "raw_style":PersonLifeDatesStyle (bracketed =True ),
        "text_status":PersonLifeStatus .unknown ,
        }
    birth_match =BIRTH_PREFIX_RE .match (cleaned )
    if birth_match :
        return {
        "birth_year":int (birth_match .group ("birth")),
        "death_year":None,
        "format_type":PersonLifeDatesFormat .living_birth_only ,
        "raw_style":PersonLifeDatesStyle (bracketed =True ,birth_prefix =birth_match .group ("prefix")),
        "text_status":PersonLifeStatus .living ,
        }
    death_match =DEATH_PREFIX_RE .match (cleaned )
    if death_match :
        return {
        "birth_year":None,
        "death_year":int (death_match .group ("death")),
        "format_type":PersonLifeDatesFormat .death_only ,
        "raw_style":PersonLifeDatesStyle (bracketed =True ,death_prefix =death_match .group ("prefix")),
        "text_status":PersonLifeStatus .deceased ,
        }
    open_match =OPEN_INTERVAL_RE .match (cleaned )
    if open_match :
        return {
        "birth_year":int (open_match .group ("birth")),
        "death_year":None,
        "format_type":PersonLifeDatesFormat .open_interval ,
        "raw_style":PersonLifeDatesStyle (
        bracketed =True ,
        dash =open_match .group ("dash"),
        space_after_dash =cleaned .endswith (" "),
        ),
        "text_status":PersonLifeStatus .living ,
        }
    closed_match =CLOSED_INTERVAL_RE .match (cleaned )
    if closed_match :
        dash =closed_match .group ("dash")
        return {
        "birth_year":int (closed_match .group ("birth")),
        "death_year":int (closed_match .group ("death")),
        "format_type":PersonLifeDatesFormat .closed_interval ,
        "raw_style":PersonLifeDatesStyle (
        bracketed =True ,
        dash =dash ,
        space_after_dash =f"{dash} "in cleaned ,
        ),
        "text_status":PersonLifeStatus .deceased ,
        }
    return None


def _infer_living_birth_prefix (mention :PersonLifeDatesMention )->str :
    sample =f"{mention .person_name } {mention .matched_text }".lower ()
    if re .search (r"[a-z]",sample ):
        return "born"
    return "р."
