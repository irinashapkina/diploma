from __future__ import annotations 

from dataclasses import dataclass ,field 


@dataclass (frozen =True )
class SourceSpec :
    name :str 
    source_type :str 
    base_url :str 
    extractor :str 
    category :str 
    priority :int 
    aliases :list [str ]=field (default_factory =list )
    concept_name :str |None =None 
    extraction_hints :dict [str ,str ]=field (default_factory =dict )


@dataclass (frozen =True )
class TechnologyRegistryEntry :
    technology_name :str 
    aliases :list [str ]
    sources :list [SourceSpec ]


JAVA_REFERENCE_REGISTRY :dict [str ,TechnologyRegistryEntry ]={
"Java":TechnologyRegistryEntry (
technology_name ="Java",
aliases =["java","jdk","openjdk"],
sources =[
SourceSpec (
name ="Oracle Java SE Support Roadmap",
source_type ="support_page",
base_url ="https://www.oracle.com/java/technologies/java-se-support-roadmap.html",
extractor ="oracle_java",
category ="language",
priority =100 ,
),
SourceSpec (
name ="OpenJDK JDK Project",
source_type ="docs",
base_url ="https://openjdk.org/projects/jdk/",
extractor ="openjdk",
category ="language",
priority =90 ,
),
],
),
"Spring Boot":TechnologyRegistryEntry (
technology_name ="Spring Boot",
aliases =["spring boot","spring"],
sources =[
SourceSpec (
name ="Spring Boot Project",
source_type ="docs",
base_url ="https://spring.io/projects/spring-boot",
extractor ="spring_boot",
category ="framework",
priority =100 ,
),
],
),
"Hibernate":TechnologyRegistryEntry (
technology_name ="Hibernate",
aliases =["hibernate","hibernate orm"],
sources =[
SourceSpec (
name ="Hibernate ORM",
source_type ="docs",
base_url ="https://hibernate.org/orm/",
extractor ="hibernate",
category ="framework",
priority =100 ,
),
],
),
"JUnit":TechnologyRegistryEntry (
technology_name ="JUnit",
aliases =["junit","junit5","junit 5"],
sources =[
SourceSpec (
name ="JUnit User Guide",
source_type ="docs",
base_url ="https://junit.org/junit5/docs/current/user-guide/",
extractor ="junit",
category ="library",
priority =100 ,
),
],
),
"Maven":TechnologyRegistryEntry (
technology_name ="Maven",
aliases =["maven","apache maven"],
sources =[
SourceSpec (
name ="Apache Maven Release History",
source_type ="release_notes",
base_url ="https://maven.apache.org/docs/history.html",
extractor ="maven",
category ="build",
priority =90 ,
),
],
),
"Gradle":TechnologyRegistryEntry (
technology_name ="Gradle",
aliases =["gradle"],
sources =[
SourceSpec (
name ="Gradle Release Notes",
source_type ="release_notes",
base_url ="https://docs.gradle.org/current/release-notes.html",
extractor ="gradle",
category ="build",
priority =90 ,
),
],
),
"Jakarta EE":TechnologyRegistryEntry (
technology_name ="Jakarta EE",
aliases =["jakarta ee","java ee","j2ee"],
sources =[
SourceSpec (
name ="Jakarta EE Specifications",
source_type ="docs",
base_url ="https://jakarta.ee/specifications/",
extractor ="jakarta_ee",
category ="framework",
priority =100 ,
),
],
),
"TLS":TechnologyRegistryEntry (
technology_name ="TLS",
aliases =["tls","ssl"],
sources =[
SourceSpec (
name ="IETF TLS RFC 8446",
source_type ="docs",
base_url ="https://datatracker.ietf.org/doc/html/rfc8446",
extractor ="tls_spec",
category ="protocol",
priority =100 ,
),
],
),
"MD5":TechnologyRegistryEntry (
technology_name ="MD5",
aliases =["md5"],
sources =[
SourceSpec (
name ="NIST Hash Functions",
source_type ="docs",
base_url ="https://csrc.nist.gov/projects/hash-functions",
extractor ="nist_hash",
category ="security",
priority =100 ,
),
],
),
"SHA":TechnologyRegistryEntry (
technology_name ="SHA",
aliases =["sha","sha1","sha-1","sha-256"],
sources =[
SourceSpec (
name ="NIST Hash Functions",
source_type ="docs",
base_url ="https://csrc.nist.gov/projects/hash-functions",
extractor ="nist_hash",
category ="security",
priority =100 ,
),
],
),
}


CONCEPT_REFERENCE_SOURCES :list [SourceSpec ]=[
SourceSpec (
name ="Oracle JVM and JRE Overview",
source_type ="docs",
base_url ="https://docs.oracle.com/javase/8/docs/technotes/guides/vm/",
extractor ="concept_summary",
category ="language",
priority =80 ,
aliases =["java virtual machine","virtual machine"],
concept_name ="JVM",
),
SourceSpec (
name ="Oracle JDK Tools and Concepts",
source_type ="docs",
base_url ="https://docs.oracle.com/en/java/javase/21/",
extractor ="concept_summary",
category ="language",
priority =80 ,
aliases =["java development kit"],
concept_name ="JDK",
),
SourceSpec (
name ="Oracle JRE Documentation Archive",
source_type ="docs",
base_url ="https://www.oracle.com/java/technologies/javase-jre8-downloads.html",
extractor ="concept_summary",
category ="language",
priority =60 ,
aliases =["java runtime environment"],
concept_name ="JRE",
),
]


def iter_registry_entries ()->list [TechnologyRegistryEntry ]:
    return list (JAVA_REFERENCE_REGISTRY .values ())


def get_registry_entry (name :str )->TechnologyRegistryEntry |None :
    lowered =name .lower ()
    for entry in JAVA_REFERENCE_REGISTRY .values ():
        if entry .technology_name .lower ()==lowered or lowered in entry .aliases :
            return entry 
    return None 
