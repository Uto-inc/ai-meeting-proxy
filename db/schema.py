"""SQLite schema definitions and migration helpers."""

import logging

import aiosqlite

logger = logging.getLogger("meeting-proxy.db")

SCHEMA_VERSION = 1

_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default',
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    token_expiry TEXT NOT NULL,
    scopes TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS meetings (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    meeting_url TEXT,
    calendar_id TEXT DEFAULT 'primary',
    ai_enabled INTEGER DEFAULT 0,
    bot_id TEXT,
    bot_status TEXT DEFAULT 'idle',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id TEXT NOT NULL REFERENCES meetings(id),
    source_type TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime_type TEXT,
    drive_file_id TEXT,
    drive_file_type TEXT,
    extracted_text TEXT,
    file_path TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS conversation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id TEXT NOT NULL REFERENCES meetings(id),
    bot_id TEXT NOT NULL,
    speaker TEXT NOT NULL,
    text TEXT NOT NULL,
    utterance_type TEXT DEFAULT 'human',
    response_category TEXT,
    timestamp TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS minutes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id TEXT NOT NULL REFERENCES meetings(id),
    summary TEXT,
    answered_items TEXT,
    taken_back_items TEXT,
    action_items TEXT,
    full_markdown TEXT,
    google_doc_id TEXT,
    google_doc_url TEXT,
    status TEXT DEFAULT 'draft',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_materials_meeting ON materials(meeting_id);
CREATE INDEX IF NOT EXISTS idx_conversation_meeting ON conversation_log(meeting_id);
CREATE INDEX IF NOT EXISTS idx_minutes_meeting ON minutes(meeting_id);
CREATE INDEX IF NOT EXISTS idx_meetings_start ON meetings(start_time);
"""


async def init_db(db_path: str) -> aiosqlite.Connection:
    """Open the database, create tables if needed, and return the connection."""
    db = await aiosqlite.connect(db_path)
    db.row_factory = aiosqlite.Row
    await db.executescript(_TABLES_SQL)

    cursor = await db.execute("SELECT MAX(version) as v FROM schema_version")
    row = await cursor.fetchone()
    current = row["v"] if row and row["v"] else 0

    if current < SCHEMA_VERSION:
        await db.execute(
            "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
        await db.commit()

    logger.info("Database initialized at %s (schema v%d)", db_path, SCHEMA_VERSION)
    return db
