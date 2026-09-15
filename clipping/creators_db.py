"""
clipping.creators_db — Creator permission registry.

The home for Feed B (creator partnerships / rev-share) from the
automation blueprint: a small local table of who has been asked, who
said yes, and on what terms. clipping.rights checks this table at
runtime before letting a "permissioned" source through — nothing in
this file makes rights decisions itself, it only records and serves
decisions a human already made.

No web UI yet; use the CLI at the bottom (`python -m clipping.creators_db ...`)
or call the functions directly.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

OUTREACH_STATUSES = [
    "not_contacted",
    "contacted",
    "negotiating",
    "agreed",
    "declined",
    "revoked",
]


def default_db_path(outputs_dir: str) -> str:
    """
    Mirrors the sibling-'data'-directory convention already used by
    clipping.phase1.deduplication (outputs_dir's parent / "data").
    """
    data_dir = os.path.join(os.path.dirname(outputs_dir.rstrip(os.sep)), "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "creators.db")


def _connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS creators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                channel_id TEXT,
                channel_name TEXT NOT NULL,
                contact_info TEXT,
                outreach_status TEXT NOT NULL DEFAULT 'not_contacted',
                revenue_share_pct REAL DEFAULT 0,
                platforms_allowed TEXT,
                content_restrictions TEXT,
                agreement_notes TEXT,
                agreed_at TEXT,
                revoked_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_creators_channel_id ON creators(channel_id)"
        )
        conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_creator(
    db_path: str,
    platform: str,
    channel_name: str,
    channel_id: Optional[str] = None,
    contact_info: Optional[str] = None,
    outreach_status: str = "not_contacted",
) -> int:
    if outreach_status not in OUTREACH_STATUSES:
        raise ValueError(f"Invalid outreach_status: {outreach_status!r}")
    init_db(db_path)
    now = _now()
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO creators
                (platform, channel_id, channel_name, contact_info,
                 outreach_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (platform, channel_id, channel_name, contact_info, outreach_status, now, now),
        )
        conn.commit()
        return cur.lastrowid


def update_status(
    db_path: str,
    creator_id: int,
    outreach_status: str,
    revenue_share_pct: Optional[float] = None,
    platforms_allowed: Optional[str] = None,
    content_restrictions: Optional[str] = None,
    agreement_notes: Optional[str] = None,
) -> None:
    if outreach_status not in OUTREACH_STATUSES:
        raise ValueError(f"Invalid outreach_status: {outreach_status!r}")
    now = _now()
    fields = {"outreach_status": outreach_status, "updated_at": now}
    if revenue_share_pct is not None:
        fields["revenue_share_pct"] = revenue_share_pct
    if platforms_allowed is not None:
        fields["platforms_allowed"] = platforms_allowed
    if content_restrictions is not None:
        fields["content_restrictions"] = content_restrictions
    if agreement_notes is not None:
        fields["agreement_notes"] = agreement_notes
    if outreach_status == "agreed":
        fields["agreed_at"] = now
    if outreach_status == "revoked":
        fields["revoked_at"] = now

    set_clause = ", ".join(f"{k} = ?" for k in fields)
    with _connect(db_path) as conn:
        conn.execute(
            f"UPDATE creators SET {set_clause} WHERE id = ?",
            (*fields.values(), creator_id),
        )
        conn.commit()


def get_creator_by_id(db_path: str, creator_id) -> Optional[sqlite3.Row]:
    if not os.path.exists(db_path):
        return None
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM creators WHERE id = ?", (int(creator_id),)
        ).fetchone()
        return row


def get_creator_by_channel(db_path: str, channel_id: str) -> Optional[sqlite3.Row]:
    if not os.path.exists(db_path):
        return None
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM creators WHERE channel_id = ? ORDER BY id DESC LIMIT 1",
            (channel_id,),
        ).fetchone()
        return row


def list_creators(db_path: str, outreach_status: Optional[str] = None) -> list[sqlite3.Row]:
    if not os.path.exists(db_path):
        return []
    with _connect(db_path) as conn:
        if outreach_status:
            return conn.execute(
                "SELECT * FROM creators WHERE outreach_status = ? ORDER BY id",
                (outreach_status,),
            ).fetchall()
        return conn.execute("SELECT * FROM creators ORDER BY id").fetchall()


# ==============================================================================
# CLI — python -m clipping.creators_db <command> ...
# ==============================================================================

def _cli() -> None:
    p = argparse.ArgumentParser(description="Creator permission registry")
    p.add_argument("--db", default=os.path.join("data", "creators.db"), help="Path to creators.db")
    sub = p.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="Register a new creator (starts as not_contacted)")
    p_add.add_argument("--platform", required=True, choices=["youtube", "twitch", "tiktok", "instagram", "other"])
    p_add.add_argument("--name", required=True, dest="channel_name")
    p_add.add_argument("--channel-id", default=None)
    p_add.add_argument("--contact", default=None, dest="contact_info")

    p_update = sub.add_parser("update", help="Update a creator's outreach status / terms")
    p_update.add_argument("id", type=int)
    p_update.add_argument("--status", required=True, dest="outreach_status", choices=OUTREACH_STATUSES)
    p_update.add_argument("--revenue-share", type=float, default=None, dest="revenue_share_pct")
    p_update.add_argument("--platforms-allowed", default=None)
    p_update.add_argument("--restrictions", default=None, dest="content_restrictions")
    p_update.add_argument("--notes", default=None, dest="agreement_notes")

    sub.add_parser("list", help="List all creators")
    p_list_status = sub.add_parser("list-status", help="List creators with a given status")
    p_list_status.add_argument("status", choices=OUTREACH_STATUSES)

    args = p.parse_args()

    if args.command == "add":
        creator_id = add_creator(
            args.db, args.platform, args.channel_name, args.channel_id, args.contact_info
        )
        print(f"✅ Added creator #{creator_id}: {args.channel_name} ({args.platform}) — status: not_contacted")

    elif args.command == "update":
        update_status(
            args.db,
            args.id,
            args.outreach_status,
            args.revenue_share_pct,
            args.platforms_allowed,
            args.content_restrictions,
            args.agreement_notes,
        )
        print(f"✅ Creator #{args.id} -> {args.outreach_status}")

    elif args.command in ("list", "list-status"):
        status_filter = args.status if args.command == "list-status" else None
        rows = list_creators(args.db, status_filter)
        if not rows:
            print("(no creators found)")
        for row in rows:
            print(
                f"#{row['id']:<4} {row['channel_name']:<30} {row['platform']:<10} "
                f"{row['outreach_status']:<14} share={row['revenue_share_pct']}%"
            )


if __name__ == "__main__":
    _cli()
