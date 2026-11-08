"""SQLite-backed opportunity ledger with source history and change tracking.

For durable Render persistence, mount a persistent disk and set
OPPORTUNITY_DB_PATH=/var/data/reinigungsradar-opportunities.sqlite3.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

from .models import Opportunity, clean_text


DEFAULT_DB_PATH = "data/opportunities.sqlite3"
TRACKED_FIELDS = (
    "title", "buyer", "description", "city", "region", "publication_date",
    "deadline", "estimated_value", "url", "category", "opportunity_type", "status",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def configured_db_path() -> str:
    return os.environ.get("OPPORTUNITY_DB_PATH", DEFAULT_DB_PATH).strip() or DEFAULT_DB_PATH


def render_storage_warning(path: str | None = None) -> str:
    path = path or configured_db_path()
    on_render = bool(os.environ.get("RENDER_SERVICE_ID") or os.environ.get("RENDER"))
    if on_render and not Path(path).expanduser().resolve().as_posix().startswith("/var/data/"):
        return (
            "هشدار ذخیره‌سازی: این سرویس Render روی فایل‌سیستم موقت اجرا می‌شود. "
            "پس از Restart یا Deploy ممکن است داده‌های فرصت‌ها از بین بروند. "
            "برای ماندگاری، دیسک پایدار متصل و OPPORTUNITY_DB_PATH روی /var/data تنظیم شود."
        )
    return ""


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _content_hash(data: dict) -> str:
    payload = {key: data.get(key) for key in TRACKED_FIELDS if key != "status"}
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


class OpportunityStore:
    def __init__(self, path: str | None = None):
        self.path = path or configured_db_path()
        if self.path != ":memory:":
            Path(self.path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self.initialise()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        if self.path != ":memory:":
            conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def initialise(self) -> None:
        with self.connect() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS sources (
                source_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                access_mode TEXT NOT NULL DEFAULT 'public',
                enabled INTEGER NOT NULL DEFAULT 1,
                last_run_at TEXT,
                last_success_at TEXT,
                last_status TEXT NOT NULL DEFAULT 'not_run',
                last_error TEXT,
                last_count INTEGER NOT NULL DEFAULT 0,
                priority INTEGER NOT NULL DEFAULT 50,
                notes TEXT
            );
            CREATE TABLE IF NOT EXISTS opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                identity_key TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                buyer TEXT,
                description TEXT,
                city TEXT,
                region TEXT,
                postal_code TEXT,
                category TEXT,
                opportunity_type TEXT,
                publication_date TEXT,
                deadline TEXT,
                estimated_value TEXT,
                currency TEXT,
                cpv TEXT,
                url TEXT,
                primary_source TEXT,
                source_priority INTEGER NOT NULL DEFAULT 50,
                score INTEGER NOT NULL DEFAULT 0,
                score_reason TEXT,
                evidence_json TEXT,
                status TEXT NOT NULL DEFAULT 'unknown',
                content_hash TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
                source_id TEXT NOT NULL REFERENCES sources(source_id),
                external_id TEXT NOT NULL,
                source_url TEXT,
                source_published_at TEXT,
                content_hash TEXT NOT NULL,
                raw_json TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                UNIQUE(source_id, external_id)
            );
            CREATE TABLE IF NOT EXISTS opportunity_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
                source_id TEXT NOT NULL,
                field TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                changed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS source_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL REFERENCES sources(source_id),
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                records_seen INTEGER NOT NULL DEFAULT 0,
                records_new INTEGER NOT NULL DEFAULT 0,
                records_changed INTEGER NOT NULL DEFAULT 0,
                error_detail TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_opportunities_deadline ON opportunities(deadline);
            CREATE INDEX IF NOT EXISTS idx_opportunities_score ON opportunities(score DESC);
            CREATE INDEX IF NOT EXISTS idx_opportunities_category ON opportunities(category);
            CREATE INDEX IF NOT EXISTS idx_observations_opportunity ON observations(opportunity_id);
            CREATE INDEX IF NOT EXISTS idx_changes_time ON opportunity_changes(changed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_runs_source_time ON source_runs(source_id, started_at DESC);
            """)

    def seed_sources(self, definitions: Iterable[dict]) -> None:
        with self.connect() as conn:
            for source in definitions:
                conn.execute("""
                    INSERT INTO sources
                    (source_id,name,kind,access_mode,enabled,priority,notes)
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(source_id) DO UPDATE SET
                        name=excluded.name, kind=excluded.kind,
                        access_mode=excluded.access_mode, priority=excluded.priority,
                        notes=excluded.notes
                """, (
                    source["source_id"], source["name"], source["kind"],
                    source.get("access_mode", "public"), int(source.get("enabled", True)),
                    int(source.get("priority", 50)), source.get("notes", ""),
                ))

    def start_run(self, source_id: str) -> int:
        now = utc_now()
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO source_runs(source_id,started_at) VALUES (?,?)",
                (source_id, now),
            )
            conn.execute(
                "UPDATE sources SET last_run_at=?,last_status='running',last_error=NULL WHERE source_id=?",
                (now, source_id),
            )
            return int(cur.lastrowid)

    def finish_run(
        self, run_id: int, source_id: str, status: str, seen: int,
        inserted: int, changed: int, error: str = "",
    ) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute("""
                UPDATE source_runs SET finished_at=?,status=?,records_seen=?,
                    records_new=?,records_changed=?,error_detail=? WHERE id=?
            """, (now, status, seen, inserted, changed, clean_text(error, 2000), run_id))
            conn.execute("""
                UPDATE sources SET last_run_at=?,last_success_at=CASE WHEN ? IN ('ok','partial') THEN ? ELSE last_success_at END,
                    last_status=?,last_error=?,last_count=? WHERE source_id=?
            """, (now, status, now, status, clean_text(error, 2000) or None, seen, source_id))

    def mark_source_status(self, source_id: str, status: str, error: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE sources SET last_status=?,last_error=? WHERE source_id=?",
                (status, clean_text(error, 2000) or None, source_id),
            )

    @staticmethod
    def _status(deadline: str) -> str:
        if not deadline:
            return "unknown"
        try:
            return "open" if date.fromisoformat(deadline[:10]) >= date.today() else "closed"
        except ValueError:
            return "unknown"

    def upsert_opportunity(self, item: Opportunity) -> dict:
        data = item.to_dict()
        now = utc_now()
        key = item.canonical_key
        content_hash = _content_hash(data)
        external_id = item.external_id or item.url or key
        inserted = False
        changed = False

        with self.connect() as conn:
            existing = conn.execute(
                "SELECT * FROM opportunities WHERE identity_key=?", (key,)
            ).fetchone()
            if existing is None:
                cur = conn.execute("""
                    INSERT INTO opportunities(
                        identity_key,title,buyer,description,city,region,postal_code,category,
                        opportunity_type,publication_date,deadline,estimated_value,currency,cpv,url,
                        primary_source,source_priority,score,score_reason,evidence_json,status,
                        content_hash,first_seen_at,last_seen_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    key, data["title"], data["buyer"], data["description"], data["city"],
                    data["region"], data["postal_code"], data["category"], data["opportunity_type"],
                    data["publication_date"], data["deadline"], data["estimated_value"], data["currency"],
                    data["cpv"], data["url"], item.source_id, item.source_priority, item.score,
                    item.score_reason, _json(item.evidence), self._status(item.deadline),
                    content_hash, now, now,
                ))
                opportunity_id = int(cur.lastrowid)
                inserted = True
            else:
                opportunity_id = int(existing["id"])
                priority = int(existing["source_priority"] or 50)
                updates = {}
                for field in TRACKED_FIELDS:
                    incoming = self._status(item.deadline) if field == "status" else data.get(field)
                    old = existing[field] if field in existing.keys() else None
                    if incoming in (None, ""):
                        continue
                    if str(old or "") != str(incoming) and (not old or item.source_priority <= priority):
                        updates[field] = incoming
                        if field in TRACKED_FIELDS:
                            conn.execute("""
                                INSERT INTO opportunity_changes(
                                    opportunity_id,source_id,field,old_value,new_value,changed_at
                                ) VALUES (?,?,?,?,?,?)
                            """, (opportunity_id, item.source_id, field, str(old or ""), str(incoming), now))
                if updates:
                    changed = True
                    assignments = ",".join(f"{field}=?" for field in updates)
                    conn.execute(
                        f"UPDATE opportunities SET {assignments},last_seen_at=?,content_hash=?,"
                        "source_priority=MIN(source_priority,?),score=MAX(score,?) WHERE id=?",
                        (*updates.values(), now, content_hash, item.source_priority, item.score, opportunity_id),
                    )
                else:
                    conn.execute(
                        "UPDATE opportunities SET last_seen_at=?,score=MAX(score,?) WHERE id=?",
                        (now, item.score, opportunity_id),
                    )

            observation = conn.execute(
                "SELECT id,content_hash FROM observations WHERE source_id=? AND external_id=?",
                (item.source_id, external_id),
            ).fetchone()
            raw_json = _json(item.raw)
            if observation is None:
                conn.execute("""
                    INSERT INTO observations(
                        opportunity_id,source_id,external_id,source_url,source_published_at,
                        content_hash,raw_json,first_seen_at,last_seen_at
                    ) VALUES (?,?,?,?,?,?,?,?,?)
                """, (
                    opportunity_id, item.source_id, external_id, item.url,
                    item.publication_date, content_hash, raw_json, now, now,
                ))
            else:
                conn.execute("""
                    UPDATE observations SET opportunity_id=?,source_url=?,source_published_at=?,
                        content_hash=?,raw_json=?,last_seen_at=? WHERE id=?
                """, (
                    opportunity_id, item.url, item.publication_date, content_hash,
                    raw_json, now, observation["id"],
                ))
                if observation["content_hash"] != content_hash:
                    changed = True

            conn.execute("""
                UPDATE opportunities SET url=CASE WHEN (url IS NULL OR url='') AND ?<>'' THEN ? ELSE url END
                WHERE id=?
            """, (item.url, item.url, opportunity_id))

            row = conn.execute(
                "SELECT COUNT(DISTINCT source_id) AS source_count FROM observations WHERE opportunity_id=?",
                (opportunity_id,),
            ).fetchone()
        return {
            "opportunity_id": opportunity_id,
            "inserted": inserted,
            "changed": changed,
            "source_count": int(row["source_count"] or 1),
        }

    def list_opportunities(
        self, query: str = "", category: str = "Alle",
        status: str = "Alle", include_jobs: bool = False, limit: int = 1000,
    ) -> list[dict]:
        sql = """
            SELECT o.*, COUNT(DISTINCT ob.source_id) AS source_count,
                   GROUP_CONCAT(DISTINCT ob.source_id) AS source_ids
            FROM opportunities o
            LEFT JOIN observations ob ON ob.opportunity_id=o.id
            WHERE 1=1
        """
        params: list = []
        if query.strip():
            needle = f"%{query.strip().casefold()}%"
            sql += " AND (LOWER(o.title) LIKE ? OR LOWER(COALESCE(o.buyer,'')) LIKE ? "
            sql += " OR LOWER(COALESCE(o.description,'')) LIKE ? OR LOWER(COALESCE(o.city,'')) LIKE ?)"
            params.extend([needle] * 4)
        if category != "Alle":
            sql += " AND o.category=?"
            params.append(category)
        if status != "Alle":
            sql += " AND o.status=?"
            params.append(status.casefold())
        if not include_jobs:
            sql += " AND COALESCE(o.opportunity_type,'')<>'job'"
        sql += " GROUP BY o.id ORDER BY o.score DESC, CASE WHEN o.deadline IS NULL OR o.deadline='' THEN 1 ELSE 0 END, o.deadline ASC, o.last_seen_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 5000)))
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def list_sources(self) -> list[dict]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM sources ORDER BY priority,name"
            ).fetchall()]

    def recent_changes(self, limit: int = 50) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("""
                SELECT c.changed_at,c.field,c.old_value,c.new_value,c.source_id,o.title,o.url
                FROM opportunity_changes c JOIN opportunities o ON o.id=c.opportunity_id
                ORDER BY c.changed_at DESC LIMIT ?
            """, (max(1, min(int(limit), 500)),)).fetchall()
            return [dict(row) for row in rows]

    def stats(self) -> dict:
        with self.connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS n FROM opportunities").fetchone()["n"]
            open_count = conn.execute("SELECT COUNT(*) AS n FROM opportunities WHERE status='open'").fetchone()["n"]
            new_24h = conn.execute(
                "SELECT COUNT(*) AS n FROM opportunities WHERE first_seen_at>=datetime('now','-1 day')"
            ).fetchone()["n"]
            changed = conn.execute(
                "SELECT COUNT(DISTINCT opportunity_id) AS n FROM opportunity_changes WHERE changed_at>=datetime('now','-7 day')"
            ).fetchone()["n"]
            active_sources = conn.execute(
                "SELECT COUNT(*) AS n FROM sources WHERE enabled=1 AND access_mode<>'manual_only'"
            ).fetchone()["n"]
        return {
            "total": int(total), "open": int(open_count), "new_24h": int(new_24h),
            "changed_7d": int(changed), "active_sources": int(active_sources),
        }
