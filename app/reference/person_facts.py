from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass (slots =True ,frozen =True )
class PersonReferenceFact :
    canonical_name :str
    birth_year :int |None
    death_year :int |None
    is_living :bool |None
    formatted_life_dates :str
    source_title :str
    source_url :str
    confidence :float
    aliases :tuple [str ,...]=()


CURATED_PERSON_REFERENCE_FACTS :tuple [PersonReferenceFact ,...]=(
PersonReferenceFact (
canonical_name ="Ноам Хомский",
birth_year =1928,
death_year =None,
is_living =True,
formatted_life_dates ="р. 1928",
source_title ="Encyclopaedia Britannica: Noam Chomsky",
source_url ="https://www.britannica.com/biography/Noam-Chomsky",
confidence =0.97,
aliases =("Noam Chomsky",),
),
PersonReferenceFact (
canonical_name ="Алан Тьюринг",
birth_year =1912,
death_year =1954,
is_living =False,
formatted_life_dates ="1912–1954",
source_title ="Encyclopaedia Britannica: Alan Turing",
source_url ="https://www.britannica.com/biography/Alan-Turing",
confidence =0.98,
aliases =("Alan Turing",),
),
PersonReferenceFact (
canonical_name ="Фердинанд де Соссюр",
birth_year =1857,
death_year =1913,
is_living =False,
formatted_life_dates ="1857–1913",
source_title ="Encyclopaedia Britannica: Ferdinand de Saussure",
source_url ="https://www.britannica.com/biography/Ferdinand-de-Saussure",
confidence =0.97,
aliases =("Ferdinand de Saussure","Фердинанд Соссюр"),
),
PersonReferenceFact (
canonical_name ="Аристотель",
birth_year =-384,
death_year =-322,
is_living =False,
formatted_life_dates ="384–322 до н. э.",
source_title ="Encyclopaedia Britannica: Aristotle",
source_url ="https://www.britannica.com/biography/Aristotle",
confidence =0.95,
aliases =("Aristotle",),
),
)


class PersonLifeDatesResolver :
    def __init__ (self ,facts :tuple [PersonReferenceFact ,...]|list [PersonReferenceFact ]|None =None )->None :
        self .facts =tuple (facts or CURATED_PERSON_REFERENCE_FACTS )

    def resolve (self ,person_name :str )->PersonReferenceFact |None :
        normalized =_normalize_person_name (person_name )
        if not normalized :
            return None
        matches :list [PersonReferenceFact ]=[]
        for fact in self .facts :
            candidate_names =(fact .canonical_name ,*fact .aliases )
            if any (_normalize_person_name (candidate )==normalized for candidate in candidate_names ):
                matches .append (fact )
        if len (matches )==1 :
            return matches [0 ]
        return None


def _normalize_person_name (value :str )->str :
    return re .sub (r"\s+"," ",re .sub (r"[^0-9A-Za-zА-Яа-яЁё -]+"," ",value )).strip ().lower ()
