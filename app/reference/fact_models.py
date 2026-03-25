from __future__ import annotations 

from dataclasses import dataclass ,field 
from typing import Any 


@dataclass (slots =True )
class ExtractedReferenceFact :
    fact_kind :str 
    current_version :str |None =None 
    current_release_year :int |None =None 
    current_label :str |None =None 
    recommended_version :str |None =None 
    latest_lts_version :str |None =None 
    min_supported_version :str |None =None 
    deprecated_versions :list [str ]|None =None 
    support_status :str |None =None 
    raw_excerpt :str |None =None 
    parser_name :str |None =None 
    confidence :float =0.0 
    diagnostics :list [str ]=field (default_factory =list )

    def to_payload (self )->dict [str ,Any ]:
        return {
        "fact_kind":self .fact_kind ,
        "current_version":self .current_version ,
        "current_release_year":self .current_release_year ,
        "current_label":self .current_label ,
        "recommended_version":self .recommended_version ,
        "latest_lts_version":self .latest_lts_version ,
        "min_supported_version":self .min_supported_version ,
        "deprecated_versions":self .deprecated_versions ,
        "support_status":self .support_status ,
        "raw_excerpt":self .raw_excerpt ,
        "parser_name":self .parser_name ,
        "confidence":self .confidence ,
        "diagnostics":self .diagnostics ,
        }


@dataclass (slots =True )
class MergedTechnologyBaseline :
    technology_name :str 
    current_version :str |None 
    current_release_year :int |None 
    current_label :str |None 
    recommended_version :str |None 
    latest_lts_version :str |None 
    min_supported_version :str |None 
    deprecated_versions :list [str ]
    support_status :str |None 
    source_title :str |None 
    source_url :str |None 
    parser_name :str |None 
    confidence :float 
    fact_kind :str 


def build_structured_summary (technology_name :str ,fact :ExtractedReferenceFact )->str :
    parts =[]
    if fact .current_label and fact .current_version :
        parts .append (f"{fact .current_label } release for {technology_name }: {fact .current_version }")
    elif fact .current_version :
        parts .append (f"Current release for {technology_name }: {fact .current_version }")
    if fact .current_release_year :
        parts .append (f"release year: {fact .current_release_year }")
    if fact .latest_lts_version and fact .latest_lts_version !=fact .current_version :
        parts .append (f"latest LTS: {fact .latest_lts_version }")
    if fact .min_supported_version :
        parts .append (f"minimum supported: {fact .min_supported_version }")
    if fact .support_status :
        parts .append (fact .support_status )
    return "; ".join (parts )if parts else f"Structured reference facts extracted for {technology_name }."
