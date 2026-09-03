"""Compile the crossword word bank into SQLite.

data/crossword_words.json is the human-editable source of truth — readable
diffs, easy to extend. This script compiles it to data/wordbank.db, which is
what the API actually queries. The database is generated, gitignored, and never
served to clients.

Run directly, or let crossword.py rebuild it on demand:

    python build_wordbank.py
"""

import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List

BASE_DIR = Path(__file__).resolve().parent
SEED_FILE = BASE_DIR / "data" / "crossword_words.json"
DB_FILE = BASE_DIR / "data" / "wordbank.db"

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE categories (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

-- A word is stored once even when several categories claim it (SALT is both
-- food and science), with the category link kept in word_categories.
CREATE TABLE words (
    id     INTEGER PRIMARY KEY,
    word   TEXT    NOT NULL,
    clue   TEXT    NOT NULL,
    length INTEGER NOT NULL,
    UNIQUE (word, clue)
);

CREATE TABLE word_categories (
    word_id     INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    PRIMARY KEY (word_id, category_id)
);

-- Length is the hot filter: the generator only wants words that fit the grid.
CREATE INDEX idx_words_length      ON words(length);
CREATE INDEX idx_wc_category       ON word_categories(category_id);
CREATE INDEX idx_wc_word           ON word_categories(word_id);
"""


def load_seed() -> Dict[str, List[Dict[str, str]]]:
    with SEED_FILE.open(encoding="utf-8") as handle:
        return json.load(handle)


def build(seed: Dict[str, List[Dict[str, str]]], destination: Path) -> Dict[str, int]:
    """Build the database at a temp path, then move it into place atomically."""
    temp = destination.with_suffix(".db.tmp")
    temp.unlink(missing_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(temp)
    try:
        connection.executescript(SCHEMA)

        word_ids: Dict[tuple, int] = {}
        skipped = 0

        for category, entries in seed.items():
            name = category.strip().lower()
            cursor = connection.execute(
                "INSERT OR IGNORE INTO categories (name) VALUES (?)", (name,)
            )
            category_id = connection.execute(
                "SELECT id FROM categories WHERE name = ?", (name,)
            ).fetchone()[0]

            for entry in entries:
                word = str(entry.get("word", "")).strip().upper()
                clue = str(entry.get("clue", "")).strip()
                if not word.isalpha() or len(word) < 2 or not clue:
                    skipped += 1
                    continue

                key = (word, clue)
                if key not in word_ids:
                    connection.execute(
                        "INSERT OR IGNORE INTO words (word, clue, length) VALUES (?, ?, ?)",
                        (word, clue, len(word)),
                    )
                    word_ids[key] = connection.execute(
                        "SELECT id FROM words WHERE word = ? AND clue = ?", key
                    ).fetchone()[0]

                connection.execute(
                    "INSERT OR IGNORE INTO word_categories (word_id, category_id) VALUES (?, ?)",
                    (word_ids[key], category_id),
                )

        connection.commit()
        stats = {
            "categories": connection.execute("SELECT COUNT(*) FROM categories").fetchone()[0],
            "words": connection.execute("SELECT COUNT(*) FROM words").fetchone()[0],
            "links": connection.execute("SELECT COUNT(*) FROM word_categories").fetchone()[0],
            "skipped": skipped,
        }
        connection.execute("VACUUM")
    finally:
        connection.close()

    os.replace(temp, destination)
    return stats


def main() -> int:
    if not SEED_FILE.is_file():
        print(f"Seed file not found: {SEED_FILE}", file=sys.stderr)
        return 1

    stats = build(load_seed(), DB_FILE)
    size_kb = DB_FILE.stat().st_size / 1024
    print(
        f"Built {DB_FILE.relative_to(BASE_DIR)} — "
        f"{stats['words']} words across {stats['categories']} categories, "
        f"{stats['links']} category links, {stats['skipped']} skipped ({size_kb:.0f} KB)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
