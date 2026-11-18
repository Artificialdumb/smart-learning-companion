"""Verified textbook and curriculum-standard locations, loaded from curriculum.json."""

from hashlib import sha256

from app.rules import curriculum

_DATA = curriculum()

# PDF pages are one-based. A tuple contains section, PDF range, and printed range.
TEXTBOOK_LOCATIONS = {
    indicator_id: tuple(
        (entry["section"], tuple(entry["pdf_pages"]), tuple(entry["printed_pages"])) for entry in entries
    )
    for indicator_id, entries in _DATA["textbook_locations"].items()
}

STANDARD_CLAUSES = {
    indicator_id: (entry["section"], *entry["clauses"])
    for indicator_id, entry in _DATA["standard_clauses"].items()
}

VERIFIED_HASHES = dict(_DATA["verified_hashes"])


def matches_verified_pdf(path, key):
    return sha256(path.read_bytes()).hexdigest() == VERIFIED_HASHES.get(key)
