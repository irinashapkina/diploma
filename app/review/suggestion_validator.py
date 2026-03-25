from __future__ import annotations 

import re 
from dataclasses import dataclass 

from app .review .context_models import SuggestionMode 

CYRILLIC_RE =re .compile (r"[А-Яа-яЁё]")
LATIN_RE =re .compile (r"[A-Za-z]")
WORD_RE =re .compile (r"\w+",re .UNICODE )
NOISY_LINE_RE =re .compile (r"^[\W\d_]{2,}$")
JAVA_STACK_COLLECTION_RE =re .compile (r"\b(stack<|java\.util\.stack|push|pop|peek|collection|deque|list)\b",re .IGNORECASE )
STACK_MEMORY_RE =re .compile (
r"\b(stack area|stack overflow|call stack|stack frame|stack memory|стек(овая)?\s+памят|область стека|переполнение стека|кадр стека)\b",
re .IGNORECASE ,
)


@dataclass (slots =True )
class ValidationResult :
    accepted :bool 
    reason :str 


def validate_suggestion (
original_text :str ,
suggested_text :str ,
mode :str |None ,
target_span :list [int ]|None =None ,
explanation :str |None =None ,
issue_type :str |None =None ,
issue_meta :dict |None =None ,
)->ValidationResult :
    if not suggested_text or suggested_text ==original_text :
        return ValidationResult (False ,"Suggestion is empty or unchanged.")
    if _language_family (original_text )!=_language_family (suggested_text ):
        return ValidationResult (False ,"Suggestion changed the primary language family.")
    if _is_ocr_heavy (original_text )and mode !=SuggestionMode .replace_span .value :
        return ValidationResult (False ,"OCR-heavy fragment should not be rewritten aggressively.")
    if mode ==SuggestionMode .replace_span .value and target_span :
        if not _changed_only_target_area (original_text ,suggested_text ,target_span ):
            return ValidationResult (False ,"Replace-span suggestion changed unrelated text.")
    if _is_definition_issue (issue_type ,issue_meta ):
        definition_validation =validate_definition_suggestion (
        original_text ,
        suggested_text ,
        explanation =explanation ,
        issue_meta =issue_meta ,
        )
        if not definition_validation .accepted :
            return definition_validation 
    if mode ==SuggestionMode .rewrite_local .value :
        if _relative_length_delta (original_text ,suggested_text )>0.45 :
            return ValidationResult (False ,"Local rewrite changed fragment length too much.")
    if _looks_garbled (suggested_text ):
        return ValidationResult (False ,"Suggestion looks garbled or layout-breaking.")
    return ValidationResult (True ,"ok")


def is_ocr_heavy_fragment (text :str )->bool :
    return _is_ocr_heavy (text )


def is_stack_collection_context (text :str )->bool :
    lowered =text .lower ()
    if STACK_MEMORY_RE .search (lowered ):
        return False 
    return bool (JAVA_STACK_COLLECTION_RE .search (lowered ))


def validate_definition_suggestion (
original_text :str ,
suggested_text :str ,
explanation :str |None =None ,
issue_meta :dict |None =None ,
)->ValidationResult :
    meta =issue_meta or {}
    concept_name =str (meta .get ("concept_name")or "").strip ()
    canonical_definition =str (meta .get ("canonical_definition")or "").strip ()
    canonical_aliases =[str (alias ).strip ()for alias in (meta .get ("canonical_aliases")or [])if str (alias ).strip ()]
    head_term =concept_name or _extract_head_term (original_text )
    if head_term and not _contains_standalone_term (suggested_text ,head_term ):
        return ValidationResult (False ,"Definition rewrite dropped the head term.")
    if _definition_expansion_conflict (head_term ,suggested_text ,canonical_definition ,canonical_aliases ):
        return ValidationResult (False ,"Definition rewrite conflicts with the canonical term expansion.")
    if explanation and _definition_expansion_conflict (head_term ,explanation ,canonical_definition ,canonical_aliases ):
        return ValidationResult (False ,"Explanation conflicts with the canonical term expansion.")
    return ValidationResult (True ,"ok")


def _language_family (text :str )->str :
    cyr =len (CYRILLIC_RE .findall (text ))
    lat =len (LATIN_RE .findall (text ))
    if cyr >lat *1.2 :
        return "cyrillic"
    if lat >cyr *1.2 :
        return "latin"
    return "mixed"


def _relative_length_delta (a :str ,b :str )->float :
    base =max (len (a ),1 )
    return abs (len (a )-len (b ))/base 


def _changed_only_target_area (original_text :str ,suggested_text :str ,target_span :list [int ])->bool :
    start ,end =int (target_span [0 ]),int (target_span [1 ])
    prefix_original =original_text [:start ]
    suffix_original =original_text [end :]
    prefix_suggested =suggested_text [:len (prefix_original )]
    suffix_suggested =suggested_text [-len (suffix_original ):]if suffix_original else ""
    return prefix_original ==prefix_suggested and suffix_original ==suffix_suggested 


def _looks_garbled (text :str )->bool :
    words =WORD_RE .findall (text )
    if not words :
        return True 
    noisy_lines =sum (1 for line in text .splitlines ()if NOISY_LINE_RE .match (line .strip ()))
    if noisy_lines >=max (3 ,len (text .splitlines ())//2 +1 ):
        return True 
    avg_word =sum (len (word )for word in words )/len (words )
    return avg_word >20 


def _is_ocr_heavy (text :str )->bool :
    lines =[line .strip ()for line in text .splitlines ()if line .strip ()]
    if len (lines )<4 :
        return False 
    short_lines =sum (1 for line in lines if len (line )<=14 )
    noisy_lines =sum (1 for line in lines if NOISY_LINE_RE .match (line ))
    digit_lines =sum (1 for line in lines if sum (char .isdigit ()for char in line )>=max (3 ,len (line )//3 ))
    return short_lines >=len (lines )//2 or noisy_lines >=3 or digit_lines >=len (lines )//2 


def _is_definition_issue (issue_type :str |None ,issue_meta :dict |None )->bool :
    issue_type_value =str (issue_type )if issue_type is not None else ""
    if issue_type_value in {"definition_inaccurate","ReviewIssueType.definition_inaccurate"}:
        return True 
    meta =issue_meta or {}
    return meta .get ("issue_family")=="definition_compare"


def _extract_head_term (text :str )->str :
    match =re .match (r"\s*([A-Za-z][A-Za-z0-9_-]{1,31})",text )
    return match .group (1 )if match else ""


def _contains_standalone_term (text :str ,term :str )->bool :
    return bool (re .search (rf"(?<![\w-]){re .escape (term )}(?![\w-])",text ,re .IGNORECASE ))


def _definition_expansion_conflict (
head_term :str ,
text :str ,
canonical_definition :str ,
canonical_aliases :list [str ],
)->bool :
    if not head_term or not text :
        return False 
    expected_expansions =_expected_expansions (canonical_definition ,canonical_aliases )
    if not expected_expansions :
        return False 
    for candidate in _extract_expansion_candidates (text ,head_term ):
        normalized =_normalize_phrase (candidate )
        if normalized and normalized not in expected_expansions :
            return True 
    return False 


def _expected_expansions (canonical_definition :str ,canonical_aliases :list [str ])->set [str ]:
    expected ={_normalize_phrase (alias )for alias in canonical_aliases if alias }
    leading_phrase =re .match (r"\s*([A-Za-z][A-Za-z -]{3,80})",canonical_definition )
    if leading_phrase :
        expected .add (_normalize_phrase (leading_phrase .group (1 )))
    return {item for item in expected if item }


def _extract_expansion_candidates (text :str ,head_term :str )->list [str ]:
    candidates :list [str ]=[]
    paren_pattern =re .compile (rf"(?<![\w-]){re .escape (head_term )}(?![\w-])\s*\(([^)]+)\)",re .IGNORECASE )
    stands_for_pattern =re .compile (
    rf"(?<![\w-]){re .escape (head_term )}(?![\w-])\s*(?:stands\s+for|расшифровывается\s+как|означает|=)\s*([^.;:\n]+)",
    re .IGNORECASE ,
    )
    for pattern in (paren_pattern ,stands_for_pattern ):
        for match in pattern .finditer (text ):
            candidates .append (match .group (1 ).strip ())
    return candidates 


def _normalize_phrase (value :str )->str :
    return re .sub (r"[^a-z0-9]+"," ",value .lower ()).strip ()
