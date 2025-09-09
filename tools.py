# tools.py
from dataclasses import dataclass
from typing import List, Dict, Optional
import re, requests
from rapidfuzz import fuzz

PUBMED_SEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_SUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
EUROPE_PMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
CROSSREF = "https://api.crossref.org/works"

@dataclass
class Source:
    key: str
    title: str
    url: str
    doi: Optional[str]
    year: Optional[int]
    oa: bool
    abstract: Optional[str] = None

def normalize(text: str) -> str:
    return re.sub(r"\s+"," ", (text or "")).strip()

def search_pubmed(query: str, retmax: int = 10) -> List[str]:
    params = {"db":"pubmed","term":query,"retmode":"json","retmax":retmax}
    r = requests.get(PUBMED_SEARCH, params=params, timeout=20)
    r.raise_for_status()
    return r.json().get("esearchresult",{}).get("idlist",[])

def fetch_pubmed_summaries(pmids: List[str]) -> List[Dict]:
    if not pmids: return []
    params = {"db":"pubmed","id":",".join(pmids),"retmode":"json"}
    r = requests.get(PUBMED_SUMMARY, params=params, timeout=20)
    r.raise_for_status()
    res = r.json().get("result",{})
    return [res[pmid] for pmid in pmids if pmid in res]

def europe_pmc_oa(query: str, pageSize: int = 10) -> List[Dict]:
    params = {"query":query + " OPEN_ACCESS:Y","format":"json","pageSize":pageSize}
    r = requests.get(EUROPE_PMC, params=params, timeout=20)
    r.raise_for_status()
    return r.json().get("resultList",{}).get("result",[])

def crossref_meta(query: str, rows: int = 5) -> List[Dict]:
    r = requests.get(CROSSREF, params={"query":query,"rows":rows}, timeout=20)
    if r.status_code != 200: return []
    return r.json().get("message",{}).get("items",[])

def build_sources_for_neuro(topic: str, need:int=3) -> List[Source]:
    """Prefer open-access neuroscience content."""
    picked: List[Source] = []

    # Europe PMC OA first
    for it in europe_pmc_oa(f"{topic} neuroscience"):
        doi = it.get("doi")
        url = f"https://europepmc.org/article/{it.get('source','MED')}/{it.get('id')}"
        picked.append(Source(
            key=f"S{len(picked)+1}",
            title=normalize(it.get("title")),
            url=url,
            doi=doi,
            year=int(it.get("pubYear")) if it.get("pubYear") else None,
            oa=True,
            abstract=normalize(it.get("abstractText"))
        ))
        if len(picked) >= need: return picked

    # PubMed summaries (may not be OA; still valid for reference)
    pmids = search_pubmed(f"{topic} neuroscience review")
    for sm in fetch_pubmed_summaries(pmids):
        title = sm.get("title")
        if not title: continue
        url = f"https://pubmed.ncbi.nlm.nih.gov/{sm.get('uid')}/"
        picked.append(Source(
            key=f"S{len(picked)+1}",
            title=normalize(title),
            url=url,
            doi=None,
            year=None,
            oa=False
        ))
        if len(picked) >= need: break
    return picked

def apa_citation(s: Source) -> str:
    base = f"{s.title}."
    if s.year: base = f"({s.year}) {base}"
    if s.doi: return f"{base} https://doi.org/{s.doi}"
    return f"{base} {s.url}"

def inline_cite(key: str) -> str:
    return f"[{key}]"

def similarity_ratio(a:str, b:str) -> float:
    return fuzz.token_set_ratio(normalize(a), normalize(b)) / 100.0
