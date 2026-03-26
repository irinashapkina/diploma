from __future__ import annotations 

import re 

from app .review .context_models import (
MentionClassification ,
MentionContext ,
PolicyAction ,
SuggestionMode ,
TermMention ,
TextSpan ,
VersionMention ,
)
from app .review .span_patch import expand_to_clause 
from app .review .suggestion_validator import is_stack_collection_context 

CURRENT_MARKERS =(
"сейчас",
"текущ",
"актуаль",
"текущая версия",
"актуальная версия",
"на сегодня",
"today",
"current",
"current version",
"latest",
"latest version",
"modern",
)
HISTORICAL_MARKERS =(
"истор",
"появ",
"выш",
"introduced",
"released",
"release",
"originally",
"в 19",
"в 20",
)
COMPARATIVE_MARKERS =(
"начиная с",
"появились",
"добавил",
"introduced",
"compare",
"сравн",
"эволюц",
"версии",
"version",
)
ENVIRONMENT_MARKERS =(
"и выше",
"or higher",
"не ниже",
"minimum",
"минималь",
"требует",
"требуется",
"require",
"окружени",
"jdk",
)
LEGACY_MARKERS =(
"legacy",
"устар",
"deprecated",
"не рекомендуется",
"вместо",
"замен",
"предпочтитель",
)
RECOMMENDATION_MARKERS =(
"используй",
"используется",
"рекоменду",
"безопас",
"следует",
"нужно",
)
DEFINITION_PATTERNS =(
re .compile (r"\s*[—:-]\s*",re .IGNORECASE ),
re .compile (r"\bэто\b",re .IGNORECASE ),
re .compile (r"\bis\b",re .IGNORECASE ),
re .compile (r"\bпредставляет собой\b",re .IGNORECASE ),
re .compile (r"\bназывается\b",re .IGNORECASE ),
re .compile (r"\bпонимается\b",re .IGNORECASE ),
)
COMPARATIVE_FEATURE_HINTS =(
"lambda",
"lambdas",
"stream api",
"default method",
"default methods",
"generics",
"for-each",
"diamond operator",
"коллекц",
"stream",
"лямбд",
"дженерик",
"for each",
)


def classify_version_mention (text :str ,mention :VersionMention )->MentionClassification :
    sentence =mention .sentence_text .lower ()
    clause_span =expand_to_clause (text ,mention .alias_span .start ,mention .version_span .end )
    clause_text =text [clause_span .start :clause_span .end ]
    clause_lower =clause_text .lower ()

    if _contains_any (clause_lower ,CURRENT_MARKERS ):
        return MentionClassification (
        context =MentionContext .current_status ,
        reason =f"Упоминание {mention .matched_text } находится внутри current-status утверждения.",
        confidence =0.92 ,
        policy_action =PolicyAction .create_issue ,
        suggestion_mode =SuggestionMode .replace_span ,
        target_span =clause_span ,
        )
    if _contains_any (clause_lower ,ENVIRONMENT_MARKERS ):
        return MentionClassification (
        context =MentionContext .environment_requirement ,
        reason =f"Упоминание {mention .matched_text } выглядит как требование к окружению.",
        confidence =0.84 ,
        policy_action =PolicyAction .ignore ,
        )
    if _looks_historical (clause_lower ,mention .version ):
        return MentionClassification (
        context =MentionContext .historical_fact ,
        reason =f"Упоминание {mention .matched_text } выглядит как исторический факт.",
        confidence =0.88 ,
        policy_action =PolicyAction .ignore ,
        )
    if _looks_comparative (sentence ):
        return MentionClassification (
        context =MentionContext .comparative_teaching ,
        reason =f"Упоминание {mention .matched_text } используется в сравнительном учебном контексте.",
        confidence =0.85 ,
        policy_action =PolicyAction .ignore ,
        )
    return MentionClassification (
    context =MentionContext .unknown ,
    reason =f"Контекст для {mention .matched_text } не удалось уверенно классифицировать.",
    confidence =0.52 ,
    policy_action =PolicyAction .review_only ,
    suggestion_mode =SuggestionMode .annotate_only ,
    )


def classify_term_mention (text :str ,mention :TermMention )->MentionClassification :
    sentence =mention .sentence_text .lower ()
    clause_span =expand_to_clause (text ,mention .term_span .start ,mention .term_span .end )
    clause_text =text [clause_span .start :clause_span .end ]
    clause_lower =clause_text .lower ()

    if mention .term =="Stack":
        if not is_stack_collection_context (clause_text ):
            return MentionClassification (
            context =MentionContext .unknown ,
            reason =f"'{mention .term }' используется вне контекста Java Collections API.",
            confidence =0.9 ,
            policy_action =PolicyAction .ignore ,
            )

    if mention .preferred_term and mention .term .lower ()!=mention .preferred_term .lower ():
        return MentionClassification (
        context =MentionContext .current_status ,
        reason =f"'{mention .term }' лучше нормализовать до '{mention .preferred_term }'.",
        confidence =0.9 ,
        policy_action =PolicyAction .create_issue ,
        suggestion_mode =SuggestionMode .replace_span ,
        target_span =mention .term_span ,
        )
    if _contains_any (clause_lower ,LEGACY_MARKERS ):
        return MentionClassification (
        context =MentionContext .legacy_warning ,
        reason =f"'{mention .term }' уже подан как legacy/deprecated пример.",
        confidence =0.86 ,
        policy_action =PolicyAction .ignore ,
        )
    if _contains_any (clause_lower ,RECOMMENDATION_MARKERS ):
        return MentionClassification (
        context =MentionContext .current_status ,
        reason =f"'{mention .term }' используется как текущая рекомендация или operational-утверждение.",
        confidence =0.83 ,
        policy_action =PolicyAction .create_issue ,
        suggestion_mode =SuggestionMode .replace_span ,
        target_span =mention .term_span ,
        )
    return MentionClassification (
    context =MentionContext .unknown ,
    reason =f"'{mention .term }' найдено без явного current-status контекста.",
    confidence =0.56 ,
    policy_action =PolicyAction .review_only ,
    suggestion_mode =SuggestionMode .annotate_only ,
    )


def is_definition_candidate (text :str ,concept_name :str ,aliases :list [str ])->tuple [bool ,TextSpan |None ]:
    sentence_lower =text .lower ()
    all_terms =[concept_name ,*aliases ]
    for term in all_terms :
        escaped_term =re .escape (term .lower ())
        standalone_term =rf"(?<![\w-]){escaped_term }(?![\w-])"
        leading_pattern =re .compile (
        rf"(^|[\n.!?]\s*){standalone_term }\s*(?:[-—:]|это|is|представляет собой|называется|понимается)",
        re .IGNORECASE ,
        )
        trailing_pattern =re .compile (
        rf"(?:под\s+)?{standalone_term }[^.!?\n]{{0,80}}(?:[-—:]|это|is|представляет собой|называется|понимается)",
        re .IGNORECASE ,
        )
        for pattern in (leading_pattern ,trailing_pattern ):
            match =pattern .search (sentence_lower )
            if not match :
                continue 
            term_match =re .search (standalone_term ,sentence_lower [match .start ():match .end ()],re .IGNORECASE )
            if not term_match :
                continue 
            start =match .start ()+term_match .start ()
            end =match .start ()+term_match .end ()
            span =expand_to_clause (text ,start ,end )
            local_text =text [span .start :span .end ]
            if any (marker .search (local_text )for marker in DEFINITION_PATTERNS ):
                return True ,span 
    return False ,None 


def _looks_comparative (sentence :str )->bool :
    version_mentions =len (re .findall (r"\b(?:java|jdk|junit|python)\s*\d+(?:\.\d+)?\b",sentence ))
    return (
    version_mentions >=2 
    or _contains_any (sentence ,COMPARATIVE_MARKERS )
    or _contains_any (sentence ,COMPARATIVE_FEATURE_HINTS )
    )


def _looks_historical (sentence :str ,version :str )->bool :
    has_old_year =bool (re .search (r"\b(19\d{2}|20(?:0\d|1\d))\b",sentence ))
    return has_old_year or _contains_any (sentence ,HISTORICAL_MARKERS )or sentence .startswith (version )


def _contains_any (text :str ,markers :tuple [str ,...])->bool :
    return any (marker in text for marker in markers )
