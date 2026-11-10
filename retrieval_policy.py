"""Keep navigation documents out of factual answers unless requested explicitly."""
from __future__ import annotations
from pathlib import Path
import re


TECHNICAL_TERMS = re.compile(
    r'\b\d{2,4}[а-яa-z]{1,4}[- ]?\d{1,4}\b|'
    r'\b(?:pps[12]?|ппс[12]?|прл(?:[- ]?27)?|мку|уми[1-8]?|пс[- ]?161)\b',
    re.IGNORECASE)


def technical_terms(question: str) -> list[str]:
    return [match.group().casefold() for match in TECHNICAL_TERMS.finditer(question)]


def allow_attachment_fragment(filename: str, text: str, question: str) -> bool:
    """Do not mix unrelated general uploads into an exact equipment lookup."""
    if not allow_source(filename, question):
        return False
    terms = technical_terms(question)
    if not terms:
        return True
    haystack = (filename + '\n' + text).casefold().replace('_', ' ')
    return any(re.search(r'\b' + re.escape(term) + (r'[12]?' if term in {'pps', 'ппс'} else '') + r'\b',
                         haystack) for term in terms)


def wants_navigation(question: str) -> bool:
    return bool(re.search(
        r'содержани[еяюи]|оглавлен|перечень\s+(?:документ|протокол)|список\s+документ|'
        r'структур[аыу]\s+(?:базы|документ)|table\s+of\s+contents|contents|document\s+list',
        question, re.IGNORECASE))


def is_navigation_source(filename: str) -> bool:
    return bool(re.search(r'содержани|оглавлен|contents|table[ _-]*of[ _-]*contents',
                          Path(filename).name, re.IGNORECASE))


def allow_source(filename: str, question: str) -> bool:
    return wants_navigation(question) or not is_navigation_source(filename)
