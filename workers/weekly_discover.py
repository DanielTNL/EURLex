# add near your other imports
from bs4 import BeautifulSoup
import feedparser
import re

def safe_soup(markup: str, prefer_xml: bool = False) -> BeautifulSoup:
    """
    Try multiple parsers so bad XML/feeds don't crash the run.
    """
    parsers_xml_first = ["lxml-xml", "xml", "lxml", "html5lib", "html.parser"]
    parsers_html_first = ["lxml", "html5lib", "html.parser", "lxml-xml", "xml"]
    chain = parsers_xml_first if prefer_xml else parsers_html_first
    last_err = None
    for p in chain:
        try:
            return BeautifulSoup(markup, p)
        except Exception as e:
            last_err = e
            print(f"[discover] parser={p} failed: {e}")
    # final fallback
    print(f"[discover] falling back to html.parser due to: {last_err}")
    return BeautifulSoup(markup, "html.parser")

def looks_like_feed(text: str, content_type: str) -> bool:
    ct = (content_type or "").lower()
    if "xml" in ct or "rss" in ct or "atom" in ct:
        return True
    head = text.lstrip()[:200].lower()
    return ("<rss" in head) or ("<feed" in head and "xmlns" in head)
