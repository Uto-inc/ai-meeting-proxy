"""Async data-access layer for all database tables."""

from __future__ import annotations

import contextlib
import json
import logging
from datetime import datetime
from typing import Any

import aiosqlite

logger = logging.getLogger("meeting-proxy.db")


class Repository:
    """Thin CRUD wrapper around an aiosqlite connection."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # OAuth tokens
    # ------------------------------------------------------------------

    async def save_token(
        self,
        access_token: str,
        refresh_token: str,
        token_expiry: str,
        scopes: str,
        user_id: str = "default",
    ) -> int:
        cursor = await self._db.execute(
            """INSERT INTO oauth_tokens
               (user_id, access_token, refresh_token, token_expiry, scopes, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))""",
            (user_id, access_token, refresh_token, token_expiry, scopes),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def get_token(self, user_id: str = "default") -> dict[str, Any] | None:
        cursor = await self._db.execute(
            "SELECT * FROM oauth_tokens WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_token(
        self,
        user_id: str,
        access_token: str,
        token_expiry: str,
    ) -> None:
        await self._db.execute(
            """UPDATE oauth_tokens
               SET access_token = ?, token_expiry = ?, updated_at = datetime('now')
               WHERE user_id = ? AND id = (
                   SELECT id FROM oauth_tokens WHERE user_id = ? ORDER BY id DESC LIMIT 1
               )""",
            (access_token, token_expiry, user_id, user_id),
        )
        await self._db.commit()

    async def delete_token(self, user_id: str = "default") -> None:
        await self._db.execute("DELETE FROM oauth_tokens WHERE user_id = ?", (user_id,))
        await self._db.commit()

    # ------------------------------------------------------------------
    # Meetings
    # ------------------------------------------------------------------

    async def upsert_meeting(self, meeting: dict[str, Any]) -> None:
        await self._db.execute(
            """INSERT INTO meetings (id, title, description, start_time, end_time,
                                     meeting_url, calendar_id, ai_enabled, bot_id, bot_status)
               VALUES (:id, :title, :description, :start_time, :end_time,
                       :meeting_url, :calendar_id, :ai_enabled, :bot_id, :bot_status)
               ON CONFLICT(id) DO UPDATE SET
                   title=excluded.title,
                   description=excluded.description,
                   start_time=excluded.start_time,
                   end_time=excluded.end_time,
                   meeting_url=excluded.meeting_url,
                   updated_at=datetime('now')""",
            meeting,
        )
        await self._db.commit()

    async def get_meeting(self, meeting_id: str) -> dict[str, Any] | None:
        cursor = await self._db.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_meetings(
        self,
        from_time: str | None = None,
        to_time: str | None = None,
        ai_enabled_only: bool = False,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM meetings WHERE 1=1"
        params: list[Any] = []
        if from_time:
            sql += " AND start_time >= ?"
            params.append(from_time)
        if to_time:
            sql += " AND start_time <= ?"
            params.append(to_time)
        if ai_enabled_only:
            sql += " AND ai_enabled = 1"
        sql += " ORDER BY start_time ASC"
        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def set_ai_enabled(self, meeting_id: str, enabled: bool) -> bool:
        cursor = await self._db.execute(
            "UPDATE meetings SET ai_enabled = ?, updated_at = datetime('now') WHERE id = ?",
            (1 if enabled else 0, meeting_id),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def update_bot_status(self, meeting_id: str, bot_id: str | None, status: str) -> None:
        await self._db.execute(
            "UPDATE meetings SET bot_id = ?, bot_status = ?, updated_at = datetime('now') WHERE id = ?",
            (bot_id, status, meeting_id),
        )
        await self._db.commit()

    # ------------------------------------------------------------------
    # Materials
    # ------------------------------------------------------------------

    async def add_material(self, material: dict[str, Any]) -> int:
        cursor = await self._db.execute(
            """INSERT INTO materials
               (meeting_id, source_type, filename, mime_type, drive_file_id,
                drive_file_type, extracted_text, file_path, status)
               VALUES (:meeting_id, :source_type, :filename, :mime_type, :drive_file_id,
                       :drive_file_type, :extracted_text, :file_path, :status)""",
            material,
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def list_materials(self, meeting_id: str) -> list[dict[str, Any]]:
        cursor = await self._db.execute(
            "SELECT * FROM materials WHERE meeting_id = ? ORDER BY created_at ASC",
            (meeting_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_material(self, material_id: int) -> dict[str, Any] | None:
        cursor = await self._db.execute("SELECT * FROM materials WHERE id = ?", (material_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_material_text(self, material_id: int, text: str, status: str = "extracted") -> None:
        await self._db.execute(
            "UPDATE materials SET extracted_text = ?, status = ? WHERE id = ?",
            (text, status, material_id),
        )
        await self._db.commit()

    async def delete_material(self, material_id: int) -> bool:
        cursor = await self._db.execute("DELETE FROM materials WHERE id = ?", (material_id,))
        await self._db.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Conversation log
    # ------------------------------------------------------------------

    async def add_conversation_entry(
        self,
        meeting_id: str,
        bot_id: str,
        speaker: str,
        text: str,
        utterance_type: str = "human",
        response_category: str | None = None,
    ) -> int:
        cursor = await self._db.execute(
            """INSERT INTO conversation_log
               (meeting_id, bot_id, speaker, text, utterance_type, response_category)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (meeting_id, bot_id, speaker, text, utterance_type, response_category),
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def get_conversation_log(self, meeting_id: str) -> list[dict[str, Any]]:
        cursor = await self._db.execute(
            "SELECT * FROM conversation_log WHERE meeting_id = ? ORDER BY timestamp ASC",
            (meeting_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Minutes
    # ------------------------------------------------------------------

    async def save_minutes(self, minutes_data: dict[str, Any]) -> int:
        for key in ("answered_items", "taken_back_items", "action_items"):
            if key in minutes_data and isinstance(minutes_data[key], list):
                minutes_data[key] = json.dumps(minutes_data[key], ensure_ascii=False)
        cursor = await self._db.execute(
            """INSERT INTO minutes
               (meeting_id, summary, answered_items, taken_back_items,
                action_items, full_markdown, status)
               VALUES (:meeting_id, :summary, :answered_items, :taken_back_items,
                       :action_items, :full_markdown, :status)
               ON CONFLICT(id) DO UPDATE SET
                   summary=excluded.summary,
                   answered_items=excluded.answered_items,
                   taken_back_items=excluded.taken_back_items,
                   action_items=excluded.action_items,
                   full_markdown=excluded.full_markdown,
                   status=excluded.status,
                   updated_at=datetime('now')""",
            minutes_data,
        )
        await self._db.commit()
        return cursor.lastrowid or 0

    async def get_minutes(self, meeting_id: str) -> dict[str, Any] | None:
        cursor = await self._db.execute(
            "SELECT * FROM minutes WHERE meeting_id = ? ORDER BY id DESC LIMIT 1",
            (meeting_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        result = dict(row)
        for key in ("answered_items", "taken_back_items", "action_items"):
            if result.get(key) and isinstance(result[key], str):
                with contextlib.suppress(json.JSONDecodeError):
                    result[key] = json.loads(result[key])
        return result

    async def update_minutes(self, meeting_id: str, updates: dict[str, Any]) -> bool:
        for key in ("answered_items", "taken_back_items", "action_items"):
            if key in updates and isinstance(updates[key], list):
                updates[key] = json.dumps(updates[key], ensure_ascii=False)
        allowed_keys = {"summary", "answered_items", "taken_back_items", "action_items", "full_markdown", "status"}
        safe_updates = {k: v for k, v in updates.items() if k in allowed_keys}
        set_parts = [f"{k} = ?" for k in safe_updates]
        set_parts.append("updated_at = datetime('now')")
        values = list(safe_updates.values()) + [meeting_id]
        sql = (
            "UPDATE minutes SET "  # noqa: S608
            + ", ".join(set_parts)
            + " WHERE meeting_id = ? AND id = ("
            "SELECT id FROM minutes WHERE meeting_id = ? ORDER BY id DESC LIMIT 1)"
        )
        cursor = await self._db.execute(
            sql,
            values + [meeting_id],
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def set_minutes_export(self, meeting_id: str, google_doc_id: str, google_doc_url: str) -> None:
        now = datetime.utcnow().isoformat()
        await self._db.execute(
            """UPDATE minutes
               SET google_doc_id = ?, google_doc_url = ?, status = 'exported', updated_at = ?
               WHERE meeting_id = ? AND id = (
                   SELECT id FROM minutes WHERE meeting_id = ? ORDER BY id DESC LIMIT 1
               )""",
            (google_doc_id, google_doc_url, now, meeting_id, meeting_id),
        )
        await self._db.commit()
