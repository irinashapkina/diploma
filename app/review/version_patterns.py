import re 

VERSION_PATTERNS :list [tuple [str ,re .Pattern [str ],str ]]=[
("Java",re .compile (r"\bJava\s*[1-8]\b",re .IGNORECASE ),"TECH_VERSION_OUTDATED"),
("Java",re .compile (r"\bJDK\s*[1-8]\b",re .IGNORECASE ),"TECH_VERSION_OUTDATED"),
("Spring",re .compile (r"\bSpring\s*[23]\b",re .IGNORECASE ),"TECH_VERSION_OUTDATED"),
("Hibernate",re .compile (r"\bHibernate\s*[34]\b",re .IGNORECASE ),"TECH_VERSION_OUTDATED"),
("JUnit",re .compile (r"\bJUnit\s*4\b",re .IGNORECASE ),"TECH_VERSION_OUTDATED"),
("TLS",re .compile (r"\bTLS\s*1\.0\b",re .IGNORECASE ),"TECH_VERSION_OUTDATED"),
("TLS",re .compile (r"\bTLS\s*1\.1\b",re .IGNORECASE ),"TECH_VERSION_OUTDATED"),
("TLS",re .compile (r"\bSSL\b",re .IGNORECASE ),"TERM_OUTDATED"),
("MD5",re .compile (r"\bMD5\b",re .IGNORECASE ),"TERM_OUTDATED"),
("SHA",re .compile (r"\bSHA-?1\b",re .IGNORECASE ),"TERM_OUTDATED"),
]
