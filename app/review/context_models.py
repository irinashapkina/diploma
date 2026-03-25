from __future__ import annotations 

from dataclasses import dataclass 
from enum import Enum 


class MentionContext (str ,Enum ):
    historical_fact ="historical_fact"
    current_status ="current_status"
    comparative_teaching ="comparative_teaching"
    environment_requirement ="environment_requirement"
    legacy_warning ="legacy_warning"
    definition ="definition"
    biographical_dates ="biographical_dates"
    unknown ="unknown"


class SuggestionMode (str ,Enum ):
    replace_span ="REPLACE_SPAN"
    annotate_only ="ANNOTATE_ONLY"
    rewrite_local ="REWRITE_LOCAL"


class PolicyAction (str ,Enum ):
    create_issue ="create_issue"
    review_only ="review_only"
    ignore ="ignore"


@dataclass (slots =True )
class TextSpan :
    start :int 
    end :int 

    def as_list (self )->list [int ]:
        return [self .start ,self .end ]


@dataclass (slots =True )
class VersionMention :
    technology :str 
    version :str 
    matched_text :str 
    alias :str 
    alias_span :TextSpan 
    version_span :TextSpan 
    sentence_span :TextSpan 
    sentence_text :str 


@dataclass (slots =True )
class TermMention :
    term :str 
    technology :str 
    matched_text :str 
    term_span :TextSpan 
    sentence_span :TextSpan 
    sentence_text :str 
    preferred_term :str |None =None 


@dataclass (slots =True )
class MentionClassification :
    context :MentionContext 
    reason :str 
    confidence :float 
    policy_action :PolicyAction 
    suggestion_mode :SuggestionMode |None =None 
    target_span :TextSpan |None =None 
