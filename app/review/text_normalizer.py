from __future__ import annotations 

CONFUSABLE_CHAR_MAP =str .maketrans (
{
"а":"a","А":"A","е":"e","Е":"E","о":"o","О":"O",
"р":"p","Р":"P","с":"c","С":"C","у":"y","У":"Y",
"х":"x","Х":"X","к":"k","К":"K","м":"m","М":"M",
"т":"t","Т":"T","в":"b","В":"B","н":"h","Н":"H",
"і":"i","І":"I",
}
)


def normalize_confusable_text (text :str )->str :
    if not text :
        return ""
    return text .translate (CONFUSABLE_CHAR_MAP )
