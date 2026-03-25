import re 

ACADEMIC_YEAR_PATTERN =re .compile (r"\b20\d{2}/20\d{2}\b")
YEAR_PATTERN =re .compile (r"\b20\d{2}\b")
FLOW_PATTERN =re .compile (r"поток\s+20\d{2}",re .IGNORECASE )
SEMESTER_PATTERN =re .compile (r"(осенний|весенний)\s+семестр\s+20\d{2}",re .IGNORECASE )
