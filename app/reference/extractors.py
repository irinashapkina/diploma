from __future__ import annotations 

import re 
from abc import ABC ,abstractmethod 
from dataclasses import dataclass 
from datetime import datetime
from html import unescape 
import calendar

from app .reference .fact_models import ExtractedReferenceFact 
from app .reference .source_registry import SourceSpec 

TAG_RE =re .compile (r"<[^>]+>")
SPACE_RE =re .compile (r"\s+")
YEAR_RE =re .compile (r"\b(20\d{2})\b")
SEMVER_RE =re .compile (r"\b(\d+(?:\.\d+){0,2})\b")
JAVA_RELEASE_RE =re .compile (r"\b(?:Java|JDK)\s*(\d{2})\b",re .IGNORECASE )
JAVA_LTS_LIST_RE =re .compile (
r"Java\s+SE\s+((?:\d+\s*,\s*)*(?:\d+\s*,?\s*(?:and\s+)?\d+))\s+are\s+LTS\s+releases",
re .IGNORECASE ,
)
OPENJDK_GA_LINE_RE =re .compile (r"(?m)^\s*(\d+)\s+\(GA\s+(\d{4})/\d{2}/\d{2}\)")
SPRING_BOOT_MAJOR_RE =re .compile (r"\bSpring Boot\s+(\d+\.\d+(?:\.\d+)?)\b",re .IGNORECASE )
SPRING_BOOT_GENERATION_RE =re .compile (r"\bVersion\s+(\d+\.\d+)\.x\b",re .IGNORECASE )
HIBERNATE_LATEST_STABLE_RE =re .compile (r"Latest stable\s*\((\d+(?:\.\d+)?)\)",re .IGNORECASE )
JAKARTA_RELEASE_RE =re .compile (r"Jakarta EE\s+(\d+)(?:\s+\(([^)]+)\))?",re .IGNORECASE )
LTS_RE =re .compile (r"\bLTS\b",re .IGNORECASE )
GA_RE =re .compile (r"\b(?:GA|General Availability|released?)\b",re .IGNORECASE )
MONTH_YEAR_RE =re .compile (
r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})\b",
re .IGNORECASE ,
)
PLANNED_MARKERS =("planned","intends","next","future")
ROADMAP_ROW_RE =re .compile (
r"\b(?P<start>\d{1,2})(?:\s*-\s*(?P<end>\d{1,2}))?\s*\((?P<label>LTS|non-LTS)\)[^A-Za-z]{0,8}(?P<month>January|February|March|April|May|June|July|August|September|October|November|December)\s*(?P<year>20\d{2})\b",
re .IGNORECASE ,
)
CURRENT_VERSION_PATTERNS =(
re .compile (r"\bcurrent(?:\s+project)?\s+version[:\s]+([0-9]+(?:\.[0-9]+){0,2})",re .IGNORECASE ),
re .compile (r"\blatest(?:\s+stable)?\s+release[:\s]+([0-9]+(?:\.[0-9]+){0,2})",re .IGNORECASE ),
re .compile (r"\brelease\s+([0-9]+(?:\.[0-9]+){0,2})",re .IGNORECASE ),
)
CURRENT_TECH_YEAR =datetime.utcnow ().year


@dataclass (slots =True )
class ExtractorResult :
    fact :ExtractedReferenceFact |None 
    diagnostics :list [str ]


class BaseReferenceExtractor (ABC ):
    parser_name ="base"

    def extract (self ,spec :SourceSpec ,html :str ,technology_name :str ,aliases :list [str ])->ExtractorResult :
        text =html_to_text (html )
        fact =self ._extract_from_text (spec ,text ,technology_name ,aliases )
        diagnostics =[]if fact else [f"{self .parser_name }: no structured fact extracted"]
        if fact :
            fact .parser_name =self .parser_name 
            if not fact .raw_excerpt :
                fact .raw_excerpt =first_excerpt (text )
        return ExtractorResult (fact =fact ,diagnostics =diagnostics )

    @abstractmethod 
    def _extract_from_text (
    self ,
    spec :SourceSpec ,
    text :str ,
    technology_name :str ,
    aliases :list [str ],
    )->ExtractedReferenceFact |None :
        raise NotImplementedError 


class OracleJavaExtractor (BaseReferenceExtractor ):
    parser_name ="oracle_java"

    def _extract_from_text (self ,spec :SourceSpec ,text :str ,technology_name :str ,aliases :list [str ])->ExtractedReferenceFact |None :
        lines =[line .strip ()for line in text .splitlines ()if line .strip ()]
        if not lines :
            lines =[text ]
        lts_list_match =JAVA_LTS_LIST_RE .search (text )
        listed_lts_versions =_parse_integer_list (lts_list_match .group (1 ))if lts_list_match else []
        lts_candidates :list [tuple [str ,int |None ,str ]]=[]
        release_candidates :list [tuple [str ,int |None ,str ]]=[]
        for roadmap_match in ROADMAP_ROW_RE .finditer (text ):
            version =roadmap_match .group ("end")or roadmap_match .group ("start")
            month =_month_to_int (roadmap_match .group ("month"))
            year =int (roadmap_match .group ("year"))
            release_date =datetime (year ,month ,1 ).date ()
            if release_date >CURRENT_TECH_DATE :
                continue 
            snippet =text [max (0 ,roadmap_match .start ()-40 ):min (len (text ),roadmap_match .end ()+60 )]
            release_candidates .append ((version ,year ,snippet ))
            if roadmap_match .group ("label").lower ()=="lts":
                lts_candidates .append ((version ,year ,snippet ))
        for line in lines :
            for match in JAVA_RELEASE_RE .finditer (line ):
                version =match .group (1 )
                if _is_planned_context (line ,match .start (),match .end ()):
                    continue 
                release_date =_extract_release_date_near (line ,match .start (),match .end ())
                if release_date and release_date >CURRENT_TECH_DATE :
                    continue 
                year =release_date .year if release_date else _extract_year (line )
                release_candidates .append ((version ,year ,line ))
                if LTS_RE .search (line )and "planned"not in line .lower ()and "next"not in line .lower ():
                    lts_candidates .append ((version ,year ,line ))
        if listed_lts_versions :
            for version in listed_lts_versions :
                if not any (existing [0 ]==version for existing in lts_candidates ):
                    lts_candidates .append ((version ,None ,f"Java SE {version } is listed as LTS release"))
        released_candidates =[item for item in release_candidates if item [1 ]is not None and item [1 ]<=CURRENT_TECH_YEAR ]
        released_lts_candidates =[item for item in lts_candidates if item [1 ]is not None and item [1 ]<=CURRENT_TECH_YEAR ]
        if not released_candidates :
            if not listed_lts_versions :
                return None 
            current_version =max (listed_lts_versions ,key =_version_key )
            return ExtractedReferenceFact (
            fact_kind ="release_baseline",
            current_version =current_version ,
            current_release_year =None ,
            current_label ="LTS",
            recommended_version =current_version ,
            latest_lts_version =current_version ,
            min_supported_version =min (listed_lts_versions ,key =_version_key ),
            support_status ="Oracle Java SE Support Roadmap",
            raw_excerpt =find_relevant_excerpt (text ,lts_list_match .group (0 )if lts_list_match else current_version ,"LTS"),
            confidence =0.95 ,
            )
        current_version ,current_year ,current_line =max (released_candidates ,key =lambda item :_version_key (item [0 ]))
        latest_lts_version =None 
        latest_lts_year =None 
        latest_lts_line =None 
        if released_lts_candidates :
            latest_lts_version ,latest_lts_year ,latest_lts_line =max (released_lts_candidates ,key =lambda item :_version_key (item [0 ]))
        elif listed_lts_versions :
            latest_lts_version =max (listed_lts_versions ,key =_version_key )
        return ExtractedReferenceFact (
        fact_kind ="release_baseline",
        current_version =current_version ,
        current_release_year =current_year ,
        current_label ="current",
        recommended_version =current_version ,
        latest_lts_version =latest_lts_version ,
        min_supported_version =min ((item [0 ]for item in released_candidates ),key =_version_key ),
        support_status ="Oracle Java SE Support Roadmap",
        raw_excerpt =find_relevant_excerpt (text ,current_line ,current_version ),
        confidence =0.96 ,
        )


class OpenJDKExtractor (BaseReferenceExtractor ):
    parser_name ="openjdk"

    def _extract_from_text (self ,spec :SourceSpec ,text :str ,technology_name :str ,aliases :list [str ])->ExtractedReferenceFact |None :
        ga_lines =OPENJDK_GA_LINE_RE .findall (text )
        if ga_lines :
            released =[(version ,int (year ))for version ,year in ga_lines if int (year )<=CURRENT_TECH_YEAR ]
            if released :
                version ,year =max (released ,key =lambda item :_version_key (item [0 ]))
                excerpt =find_relevant_excerpt (text ,f"{version } (GA {year }")
                return ExtractedReferenceFact (
                fact_kind ="release_baseline",
                current_version =version ,
                current_release_year =year ,
                current_label ="GA",
                recommended_version =version ,
                raw_excerpt =excerpt ,
                confidence =0.95 ,
                )
        candidates :list [tuple [str ,int |None ,str ]]=[]
        sentences =re .split (r"(?<=[.!?])\s+",text )
        for sentence in sentences :
            year =_extract_year (sentence )
            if year is None or year >CURRENT_TECH_YEAR :
                continue 
            if not GA_RE .search (sentence ):
                continue 
            for match in JAVA_RELEASE_RE .finditer (sentence ):
                candidates .append ((match .group (1 ),year ,sentence ))
        if not candidates :
            return None 
        version ,year ,excerpt =max (candidates ,key =lambda item :_version_key (item [0 ]))
        return ExtractedReferenceFact (
        fact_kind ="release_baseline",
        current_version =version ,
        current_release_year =year ,
        current_label ="GA",
        recommended_version =version ,
        raw_excerpt =excerpt ,
        confidence =0.9 ,
        )


class SpringBootExtractor (BaseReferenceExtractor ):
    parser_name ="spring_boot"

    def _extract_from_text (self ,spec :SourceSpec ,text :str ,technology_name :str ,aliases :list [str ])->ExtractedReferenceFact |None :
        version =(
        _match_any (CURRENT_VERSION_PATTERNS ,text )
        or _match_group (SPRING_BOOT_MAJOR_RE ,text )
        or _match_group (SPRING_BOOT_GENERATION_RE ,text )
        or _first_semver (text )
        )
        if version is None :
            return None 
        return ExtractedReferenceFact (
        fact_kind ="release_baseline",
        current_version =version ,
        current_release_year =_extract_year (find_relevant_excerpt (text ,version )),
        current_label ="stable",
        recommended_version =version ,
        raw_excerpt =find_relevant_excerpt (text ,version ),
        confidence =0.9 ,
        )


class GenericVersionExtractor (BaseReferenceExtractor ):
    parser_name ="generic_version"

    def _extract_from_text (self ,spec :SourceSpec ,text :str ,technology_name :str ,aliases :list [str ])->ExtractedReferenceFact |None :
        version =_match_any (CURRENT_VERSION_PATTERNS ,text )or _first_semver (text )
        if version is None :
            return None 
        return ExtractedReferenceFact (
        fact_kind ="release_baseline",
        current_version =version ,
        current_release_year =_extract_year (find_relevant_excerpt (text ,version )),
        current_label =spec .extraction_hints .get ("default_label")if spec .extraction_hints else "current",
        recommended_version =version ,
        raw_excerpt =find_relevant_excerpt (text ,version ),
        confidence =0.78 ,
        )


class JakartaEEExtractor (GenericVersionExtractor ):
    parser_name ="jakarta_ee"

    def _extract_from_text (self ,spec :SourceSpec ,text :str ,technology_name :str ,aliases :list [str ])->ExtractedReferenceFact |None :
        released :list [str ]=[]
        for match in JAKARTA_RELEASE_RE .finditer (text ):
            version =match .group (1 )
            status =(match .group (2 )or "").lower ()
            if "wip"in status or "work in progress"in status :
                continue 
            released .append (version )
        if not released :
            return None 
        version =max (released ,key =_version_key )
        return ExtractedReferenceFact (
        fact_kind ="release_baseline",
        current_version =version ,
        current_release_year =_extract_year (find_relevant_excerpt (text ,f"Jakarta EE {version }")or text ),
        current_label ="stable",
        recommended_version =version ,
        raw_excerpt =find_relevant_excerpt (text ,f"Jakarta EE {version }")or first_excerpt (text ),
        confidence =0.92 ,
        )


class JUnitExtractor (GenericVersionExtractor ):
    parser_name ="junit"


class MavenExtractor (GenericVersionExtractor ):
    parser_name ="maven"


class GradleExtractor (GenericVersionExtractor ):
    parser_name ="gradle"


class HibernateExtractor (GenericVersionExtractor ):
    parser_name ="hibernate"

    def _extract_from_text (self ,spec :SourceSpec ,text :str ,technology_name :str ,aliases :list [str ])->ExtractedReferenceFact |None :
        version =_match_group (HIBERNATE_LATEST_STABLE_RE ,text )
        if version is None :
            version =_match_any (CURRENT_VERSION_PATTERNS ,text )
        if version is None :
            return None 
        return ExtractedReferenceFact (
        fact_kind ="release_baseline",
        current_version =version ,
        current_release_year =_extract_year (find_relevant_excerpt (text ,f"Latest stable ({version })")or text ),
        current_label ="latest stable",
        recommended_version =version ,
        raw_excerpt =find_relevant_excerpt (text ,f"Latest stable ({version })")or first_excerpt (text ),
        confidence =0.95 ,
        )


class TLSSpecExtractor (BaseReferenceExtractor ):
    parser_name ="tls_spec"

    def _extract_from_text (self ,spec :SourceSpec ,text :str ,technology_name :str ,aliases :list [str ])->ExtractedReferenceFact |None :
        excerpt =find_relevant_excerpt (text ,"TLS 1.3","RFC 8446")or first_excerpt (text )
        return ExtractedReferenceFact (
        fact_kind ="security_baseline",
        current_version ="1.3",
        current_release_year =2018 ,
        current_label ="specification",
        recommended_version ="1.3",
        min_supported_version ="1.2",
        deprecated_versions =["1.0","1.1","SSL"],
        support_status ="TLS 1.3 defined by RFC 8446",
        raw_excerpt =excerpt ,
        confidence =0.97 ,
        )


class NISTHashExtractor (BaseReferenceExtractor ):
    parser_name ="nist_hash"

    def _extract_from_text (self ,spec :SourceSpec ,text :str ,technology_name :str ,aliases :list [str ])->ExtractedReferenceFact |None :
        if technology_name =="MD5":
            return ExtractedReferenceFact (
            fact_kind ="security_baseline",
            support_status ="MD5 is not recommended for secure collision-resistant uses",
            deprecated_versions =["MD5"],
            raw_excerpt =find_relevant_excerpt (text ,"MD5")or first_excerpt (text ),
            confidence =0.9 ,
            )
        return ExtractedReferenceFact (
        fact_kind ="security_baseline",
        current_version ="SHA-256",
        recommended_version ="SHA-256",
        deprecated_versions =["SHA-1"],
        support_status ="Prefer SHA-256 or stronger hash functions",
        raw_excerpt =find_relevant_excerpt (text ,"SHA")or first_excerpt (text ),
        confidence =0.9 ,
        )


class ConceptSummaryExtractor (BaseReferenceExtractor ):
    parser_name ="concept_summary"

    def _extract_from_text (self ,spec :SourceSpec ,text :str ,technology_name :str ,aliases :list [str ])->ExtractedReferenceFact |None :
        return ExtractedReferenceFact (
        fact_kind ="concept_summary",
        raw_excerpt =find_relevant_excerpt (text ,spec .concept_name or technology_name )or first_excerpt (text ),
        confidence =0.7 ,
        )


EXTRACTOR_REGISTRY :dict [str ,BaseReferenceExtractor ]={
"oracle_java":OracleJavaExtractor (),
"openjdk":OpenJDKExtractor (),
"spring_boot":SpringBootExtractor (),
"hibernate":HibernateExtractor (),
"junit":JUnitExtractor (),
"maven":MavenExtractor (),
"gradle":GradleExtractor (),
"jakarta_ee":JakartaEEExtractor (),
"tls_spec":TLSSpecExtractor (),
"nist_hash":NISTHashExtractor (),
"concept_summary":ConceptSummaryExtractor (),
"generic_version":GenericVersionExtractor (),
}


def get_extractor (name :str )->BaseReferenceExtractor :
    return EXTRACTOR_REGISTRY .get (name ,EXTRACTOR_REGISTRY ["generic_version"])


def html_to_text (html :str )->str :
    text =TAG_RE .sub (" ",html )
    text =unescape (text )
    text =text .replace ("\xa0"," ")
    text =SPACE_RE .sub (" ",text )
    return text .strip ()


def find_relevant_excerpt (text :str ,*needles :str )->str |None :
    lowered =text .lower ()
    positions =[lowered .find (needle .lower ())for needle in needles if needle ]
    positions =[pos for pos in positions if pos >=0 ]
    if not positions :
        return None 
    start =max (0 ,min (positions )-120 )
    end =min (len (text ),max (positions )+240 )
    return text [start :end ].strip ()


def first_excerpt (text :str ,limit :int =320 )->str :
    return text [:limit ].strip ()


def _extract_year (text :str |None )->int |None :
    if not text :
        return None 
    match =YEAR_RE .search (text )
    return int (match .group (1 ))if match else None 


def _match_any (patterns :tuple [re .Pattern [str ],...],text :str )->str |None :
    for pattern in patterns :
        match =pattern .search (text )
        if match :
            return match .group (1 )
    return None 


def _match_group (pattern :re .Pattern [str ],text :str )->str |None :
    match =pattern .search (text )
    return match .group (1 )if match else None 


def _first_semver (text :str )->str |None :
    match =SEMVER_RE .search (text )
    return match .group (1 )if match else None 


def _parse_integer_list (value :str )->list [str ]:
    return re .findall (r"\d+",value )


def _version_key (value :str )->tuple [int ,...]:
    return tuple (int (part )for part in value .split ("."))


CURRENT_TECH_DATE =datetime .utcnow ().date ()


def _is_planned_context (text :str ,start :int ,end :int )->bool :
    left =max (0 ,start -60 )
    right =min (len (text ),end +60 )
    window =text [left :right ].lower ()
    return any (marker in window for marker in PLANNED_MARKERS )


def _extract_release_date_near (text :str ,start :int ,end :int ):
    window =text [max (0 ,start -32 ):min (len (text ),end +64 )]
    match =MONTH_YEAR_RE .search (window )
    if not match :
        return None 
    month_name =match .group (1 )
    year =int (match .group (2 ))
    month =list (calendar .month_name ).index (month_name .capitalize ())
    return datetime (year ,month ,1 ).date ()


def _month_to_int (month_name :str )->int :
    return list (calendar .month_name ).index (month_name .capitalize ())
