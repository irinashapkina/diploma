from __future__ import annotations 

from app .review .context_models import TextSpan 

SENTENCE_BOUNDARIES =".!?\n"
CLAUSE_BOUNDARIES =",;:\n"


def expand_to_sentence (text :str ,start :int ,end :int )->TextSpan :
    left =start 
    right =end 
    while left >0 and text [left -1 ]not in SENTENCE_BOUNDARIES :
        left -=1 
    while right <len (text )and text [right ]not in SENTENCE_BOUNDARIES :
        right +=1 
    return TextSpan (_trim_left (text ,left ,start ),_trim_right (text ,right ,end ))


def expand_to_clause (text :str ,start :int ,end :int )->TextSpan :
    left =start 
    right =end 
    while left >0 and text [left -1 ]not in CLAUSE_BOUNDARIES and text [left -1 ]not in SENTENCE_BOUNDARIES :
        left -=1 
    while right <len (text )and text [right ]not in CLAUSE_BOUNDARIES and text [right ]not in SENTENCE_BOUNDARIES :
        right +=1 
    return TextSpan (_trim_left (text ,left ,start ),_trim_right (text ,right ,end ))


def replace_span (text :str ,span :TextSpan |list [int ]|tuple [int ,int ],replacement :str )->str :
    start ,end =_coerce_span (span )
    return f"{text [:start ]}{replacement }{text [end :]}"


def slice_span (text :str ,span :TextSpan |list [int ]|tuple [int ,int ])->str :
    start ,end =_coerce_span (span )
    return text [start :end ]


def _coerce_span (span :TextSpan |list [int ]|tuple [int ,int ])->tuple [int ,int ]:
    if isinstance (span ,TextSpan ):
        return span .start ,span .end 
    return int (span [0 ]),int (span [1 ])


def _trim_left (text :str ,left :int ,fallback :int )->int :
    while left <fallback and left <len (text )and text [left ].isspace ():
        left +=1 
    return left 


def _trim_right (text :str ,right :int ,fallback :int )->int :
    while right >fallback and text [right -1 ].isspace ():
        right -=1 
    return right 


def adjust_to_token_boundaries (text :str ,span :TextSpan |list [int ]|tuple [int ,int ])->TextSpan :
    start ,end =_coerce_span (span )
    while start >0 and _is_token_char (text [start -1 ])and start <len (text )and _is_token_char (text [start ]):
        start -=1 
    while end <len (text )and end >0 and _is_token_char (text [end -1 ])and _is_token_char (text [end ]):
        end +=1 
    return TextSpan (start ,end )


def is_boundary_safe_span (text :str ,span :TextSpan |list [int ]|tuple [int ,int ])->bool :
    start ,end =_coerce_span (span )
    if start <0 or end >len (text )or start >=end :
        return False 
    left_ok =start ==0 or not (_is_token_char (text [start -1 ])and _is_token_char (text [start ]))
    right_ok =end ==len (text )or not (_is_token_char (text [end -1 ])and _is_token_char (text [end ]))
    return left_ok and right_ok


def _is_token_char (char :str )->bool :
    return char .isalnum ()or char in "._-"
