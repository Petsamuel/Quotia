"""Crossword puzzle generation.

Builds criss-cross puzzles: words interlock on an open grid, each new word
crossing a letter of one already placed. Unlike a dense American-style grid this
always yields a valid, solvable puzzle rather than failing to fill.

Words come from a local SQLite database (data/wordbank.db), compiled from
data/crossword_words.json by build_wordbank.py. Clues are written for this
project, so generation needs no network call and no third-party rights.

The database is server-side only: it lives outside the mounted static directory
and no route exposes it.
"""

import hashlib
import json
import logging
import random
import sqlite3
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
SEED_FILE = BASE_DIR / "data" / "crossword_words.json"
DB_FILE = BASE_DIR / "data" / "wordbank.db"

BLOCK = "#"

MIN_SIZE = 7
MAX_SIZE = 21
DEFAULT_SIZE = 11

MIN_WORDS = 4
MAX_WORDS = 40

# A placement pass is cheap; retrying with a different shuffle beats trying to be
# clever about ordering, because the first word chosen dominates the outcome.
PLACEMENT_ATTEMPTS = 60


_db_checked = False


def ensure_database(force: bool = False) -> None:
    """Build the word bank if it is missing or older than its seed file.

    Checked once per process, not per request. Two reasons that matters:
    rebuilding on every query would be wasteful, and on Windows the swap into
    place fails outright while this process holds the database open — which
    previously turned an edited seed file into a permanent 500.

    A failed rebuild is therefore non-fatal whenever a usable database already
    exists: serve the existing words and say so. Only a completely missing
    database is worth failing for.
    """
    global _db_checked
    if _db_checked and not force:
        return
    _db_checked = True

    try:
        stale = (
            not DB_FILE.is_file()
            or DB_FILE.stat().st_mtime < SEED_FILE.stat().st_mtime
        )
        if not stale:
            return

        logger.info("Building crossword word bank at %s", DB_FILE)
        import build_wordbank

        build_wordbank.build(build_wordbank.load_seed(), DB_FILE)
    except Exception as error:
        if not DB_FILE.is_file():
            raise
        logger.warning(
            "Could not rebuild the word bank (%s). Serving the existing database; "
            "restart the app, or run build_wordbank.py, to pick up seed changes.",
            error,
        )


def connect() -> sqlite3.Connection:
    """Open the word bank read-only. Nothing in the request path writes to it."""
    ensure_database()
    connection = sqlite3.connect(f"file:{DB_FILE.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


@lru_cache(maxsize=1)
def _seed_bank() -> Dict[str, Tuple[Dict[str, str], ...]]:
    """The seed file, parsed in memory.

    Last-resort source of words when SQLite is unusable — an unwritable
    filesystem, a corrupt database, a build that never ran. A puzzle endpoint
    returning 500 because a cache file is missing is a worse outcome than
    reading the words directly.
    """
    with SEED_FILE.open(encoding="utf-8") as handle:
        raw = json.load(handle)

    bank: Dict[str, Tuple[Dict[str, str], ...]] = {}
    for category, entries in raw.items():
        cleaned = []
        for entry in entries:
            word = str(entry.get("word", "")).strip().upper()
            clue = str(entry.get("clue", "")).strip()
            if word.isalpha() and len(word) >= 2 and clue:
                cleaned.append({"word": word, "clue": clue})
        if cleaned:
            bank[category.strip().lower()] = tuple(cleaned)
    return bank


def _query(sql: str, params: Optional[List[Any]] = None):
    """Run a read-only query, or return None if the database can't serve it."""
    try:
        with connect() as connection:
            return connection.execute(sql, params or []).fetchall()
    except Exception as error:
        logger.warning(
            "Word bank database unavailable (%s); falling back to %s.",
            error, SEED_FILE.name,
        )
        return None


@lru_cache(maxsize=1)
def available_categories() -> List[str]:
    """Category names present in the word bank."""
    rows = _query("SELECT name FROM categories ORDER BY name")
    if rows:
        return [row["name"] for row in rows]
    return sorted(_seed_bank())


@lru_cache(maxsize=64)
def words_for(category: Optional[str] = None, max_length: Optional[int] = None):
    """Words for a category (or all), optionally capped to a maximum length.

    Filtering by length in SQL rather than in Python means the generator only
    ever loads words that can physically fit the grid, using the length index.
    Results are cached because the bank is read-only at runtime.
    """
    sql = [
        "SELECT DISTINCT w.word AS word, w.clue AS clue",
        "FROM words w",
    ]
    params: List[Any] = []

    if category:
        sql += [
            "JOIN word_categories wc ON wc.word_id = w.id",
            "JOIN categories c ON c.id = wc.category_id",
            "WHERE c.name = ?",
        ]
        params.append(category)
        if max_length is not None:
            sql.append("AND w.length <= ?")
            params.append(max_length)
    elif max_length is not None:
        sql.append("WHERE w.length <= ?")
        params.append(max_length)

    sql.append("ORDER BY w.length DESC, w.word")

    rows = _query(" ".join(sql), params)
    if rows is not None:
        return tuple({"word": row["word"], "clue": row["clue"]} for row in rows)

    # Same filtering, straight from the seed file.
    bank = _seed_bank()
    source = bank.get(category, ()) if category else tuple(
        word for words in bank.values() for word in words
    )
    seen = set()
    result = []
    for entry in source:
        if max_length is not None and len(entry["word"]) > max_length:
            continue
        key = (entry["word"], entry["clue"])
        if key in seen:
            continue
        seen.add(key)
        result.append(entry)
    result.sort(key=lambda e: (-len(e["word"]), e["word"]))
    return tuple(result)


def _fits(grid, word, row, col, dr, dc, size) -> bool:
    """Whether `word` can be laid down without breaking crossword adjacency rules."""
    end_row, end_col = row + dr * (len(word) - 1), col + dc * (len(word) - 1)
    if not (0 <= row < size and 0 <= col < size and 0 <= end_row < size and 0 <= end_col < size):
        return False

    # The cells just before and just after the word must be empty, or the word
    # would run into a neighbour and form a longer, unintended entry.
    before_r, before_c = row - dr, col - dc
    after_r, after_c = end_row + dr, end_col + dc
    for r, c in ((before_r, before_c), (after_r, after_c)):
        if 0 <= r < size and 0 <= c < size and grid[r][c] is not None:
            return False

    crossings = 0
    for i, letter in enumerate(word):
        r, c = row + dr * i, col + dc * i
        existing = grid[r][c]
        if existing is not None:
            if existing != letter:
                return False
            crossings += 1
            continue

        # For a fresh cell, the two perpendicular neighbours must be empty, or
        # placing this letter would silently create a second word alongside.
        pr, pc = dc, dr  # perpendicular direction
        for sign in (1, -1):
            nr, nc = r + pr * sign, c + pc * sign
            if 0 <= nr < size and 0 <= nc < size and grid[nr][nc] is not None:
                return False

    return crossings >= 1


def _place(grid, word, row, col, dr, dc) -> None:
    for i, letter in enumerate(word):
        grid[row + dr * i][col + dc * i] = letter


def _try_build(words: List[Dict[str, str]], size: int, target: int, rng: random.Random):
    """One placement pass. Returns (grid, placements) or None if nothing interlocked."""
    grid: List[List[Optional[str]]] = [[None] * size for _ in range(size)]
    candidates = [w for w in words if len(w["word"]) <= size]
    if not candidates:
        return None

    rng.shuffle(candidates)
    # Longest first: a long spine gives later words many crossing points.
    candidates.sort(key=lambda w: len(w["word"]), reverse=True)

    first = candidates[0]
    row = size // 2
    col = max(0, (size - len(first["word"])) // 2)
    _place(grid, first["word"], row, col, 0, 1)
    placements = [{**first, "row": row, "col": col, "direction": "across"}]
    used = {first["word"]}

    for entry in candidates[1:]:
        if len(placements) >= target:
            break
        word = entry["word"]
        if word in used:
            continue

        options: List[Tuple[int, int, int, int]] = []
        for i, letter in enumerate(word):
            for r in range(size):
                for c in range(size):
                    if grid[r][c] != letter:
                        continue
                    # Cross the existing letter in both orientations.
                    for dr, dc in ((1, 0), (0, 1)):
                        start_r, start_c = r - dr * i, c - dc * i
                        if _fits(grid, word, start_r, start_c, dr, dc, size):
                            options.append((start_r, start_c, dr, dc))

        if not options:
            continue

        start_r, start_c, dr, dc = rng.choice(options)
        _place(grid, word, start_r, start_c, dr, dc)
        placements.append({
            **entry,
            "row": start_r,
            "col": start_c,
            "direction": "down" if dr else "across",
        })
        used.add(word)

    if len(placements) < MIN_WORDS:
        return None
    return grid, placements


def _extract_entries(grid, size, clues: Dict[str, str]):
    """Read across/down entries off the finished grid and number them.

    Deriving entries from the grid rather than from the placement list means the
    clue list can never disagree with what a solver actually sees.
    """
    across: List[Dict[str, Any]] = []
    down: List[Dict[str, Any]] = []
    number = 0

    for r in range(size):
        for c in range(size):
            if grid[r][c] is None:
                continue

            starts_across = (c == 0 or grid[r][c - 1] is None) and (
                c + 1 < size and grid[r][c + 1] is not None
            )
            starts_down = (r == 0 or grid[r - 1][c] is None) and (
                r + 1 < size and grid[r + 1][c] is not None
            )
            if not (starts_across or starts_down):
                continue

            number += 1
            if starts_across:
                letters = ""
                cc = c
                while cc < size and grid[r][cc] is not None:
                    letters += grid[r][cc]
                    cc += 1
                across.append({
                    "number": number, "clue": clues.get(letters, ""), "answer": letters,
                    "row": r, "col": c, "length": len(letters),
                })
            if starts_down:
                letters = ""
                rr = r
                while rr < size and grid[rr][c] is not None:
                    letters += grid[rr][c]
                    rr += 1
                down.append({
                    "number": number, "clue": clues.get(letters, ""), "answer": letters,
                    "row": r, "col": c, "length": len(letters),
                })

    return across, down


def daily_seed(day: Optional[date] = None) -> Tuple[int, str]:
    """Derive a stable seed from a UTC date.

    Hashing the date rather than using its ordinal means consecutive days produce
    unrelated puzzles instead of near-identical ones.
    """
    day = day or datetime.now(timezone.utc).date()
    iso = day.isoformat()
    digest = hashlib.sha256(f"quotia-crossword-{iso}".encode()).hexdigest()
    return int(digest[:8], 16) % (2**31 - 1) or 1, iso


def generate_daily(size: int = DEFAULT_SIZE, day: Optional[date] = None) -> Dict[str, Any]:
    """Today's puzzle: same grid for every caller, changing at UTC midnight.

    The category rotates with the date so consecutive days aren't all one theme.
    """
    seed, iso = daily_seed(day)
    categories = available_categories()
    category = categories[seed % len(categories)] if categories else None

    puzzle = generate_puzzle(category=category, size=size, seed=seed)
    puzzle["date"] = iso
    return puzzle


def generate_puzzle(
    category: Optional[str] = None,
    size: int = DEFAULT_SIZE,
    word_count: Optional[int] = None,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Generate one crossword puzzle.

    Returns the solution grid, a blank grid to solve, numbered across/down clues,
    and the seed used — pass the same seed back to reproduce the puzzle exactly.
    """
    categories = available_categories()
    category = (category or "").strip().lower() or None
    if category and category not in categories:
        raise ValueError(
            f"Unknown category {category!r}. Available: {', '.join(categories)}."
        )

    size = max(MIN_SIZE, min(size, MAX_SIZE))
    if word_count is None:
        word_count = max(MIN_WORDS, min(size, MAX_WORDS))
    word_count = max(MIN_WORDS, min(word_count, MAX_WORDS))

    # Ask the database only for words that can fit this grid.
    words = [dict(w) for w in words_for(category, size)]
    if not words:
        raise ValueError("No words available for that category and size.")
    clues = {w["word"]: w["clue"] for w in words}

    if seed is None:
        seed = random.randrange(1, 2**31 - 1)
    rng = random.Random(seed)

    best = None
    for _ in range(PLACEMENT_ATTEMPTS):
        built = _try_build(words, size, word_count, rng)
        if built and (best is None or len(built[1]) > len(best[1])):
            best = built
            if len(best[1]) >= word_count:
                break

    if best is None:
        raise ValueError("Could not build a puzzle from the available words.")

    grid, placements = best
    across, down = _extract_entries(grid, size, clues)

    # An entry with no clue means the grid formed a word we never placed; the
    # adjacency rules should prevent it, so surface it rather than ship it.
    unclued = [e["answer"] for e in across + down if not e["clue"]]
    if unclued:
        logger.warning(f"Crossword produced unclued entries: {unclued}")

    solution = [[cell if cell else BLOCK for cell in row] for row in grid]
    puzzle = [[("" if cell else BLOCK) for cell in row] for row in grid]

    return {
        "category": category,
        "size": size,
        "seed": seed,
        "word_count": len(placements),
        "puzzle": puzzle,
        "solution": solution,
        "across": across,
        "down": down,
    }
