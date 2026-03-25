from __future__ import annotations 

import re 

from app .review .context_models import TextSpan ,VersionMention 
from app .review .span_patch import expand_to_sentence 

TECH_ALIASES :dict [str ,list [str ]]={
"Java":["java"],
"JDK":["jdk"],
"Spring Boot":["spring boot"],
"Spring":["spring"],
"Hibernate":["hibernate"],
"JUnit":["junit"],
"Maven":["maven"],
"Gradle":["gradle"],
"Jakarta EE":["jakarta ee","java ee","j2ee"],
"TLS":["tls","ssl"],
"Python":["python"],
}

VERSION_CHAIN_RE =re .compile (
r"^\s*(v?\d+(?:\.\d+){0,2})(?:\s*/\s*(v?\d+(?:\.\d+){0,2}))*",
re .IGNORECASE ,
)
VERSION_RE =re .compile (r"v?\d+(?:\.\d+){0,2}",re .IGNORECASE )
CLAUSE_STOP_RE =re .compile (r"[,;:\n!?]")


def extract_technology_versions (text :str )->list [VersionMention ]:
    lowered =text .lower ()
    results :list [VersionMention ]=[]

    for technology ,aliases in TECH_ALIASES .items ():
        for alias in aliases :
            for alias_match in re .finditer (re .escape (alias ),lowered ):
                tail =text [alias_match .end ():]
                stop_match =CLAUSE_STOP_RE .search (tail )
                segment =tail [:stop_match .start ()]if stop_match else tail 
                chain_match =VERSION_CHAIN_RE .search (segment )
                if not chain_match :
                    continue 
                chain_text =chain_match .group (0 )
                for version_match in VERSION_RE .finditer (chain_text ):
                    version =version_match .group (0 ).lstrip ("vV")
                    version_start =alias_match .end ()+version_match .start ()
                    version_end =alias_match .end ()+version_match .end ()
                    sentence_span =expand_to_sentence (text ,alias_match .start (),version_end )
                    results .append (
                    VersionMention (
                    technology =technology ,
                    version =version ,
                    matched_text =text [alias_match .start ():version_end ],
                    alias =alias ,
                    alias_span =TextSpan (alias_match .start (),alias_match .end ()),
                    version_span =TextSpan (version_start ,version_end ),
                    sentence_span =sentence_span ,
                    sentence_text =text [sentence_span .start :sentence_span .end ],
                    )
                    )

    unique :list [VersionMention ]=[]
    seen :set [tuple [str ,str ,int ,int ]]=set ()
    for item in results :
        key =(item .technology ,item .version ,item .alias_span .start ,item .version_span .start )
        if key in seen :
            continue 
        seen .add (key )
        unique .append (item )
    return unique 
