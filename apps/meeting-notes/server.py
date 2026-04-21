"""
Meeting Notes API — Python/Flask + SQLite (no external deps beyond flask).
"""
import os
import sqlite3
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

# ── Config ────────────────────────────────────────────────────────────────────

APP_DIR = Path(__file__).parent
DB_PATH = os.environ.get("DATABASE_PATH", str(APP_DIR / "data" / "meetings.db"))
PORT = int(os.environ.get("PORT", 3456))

app = Flask(__name__, static_folder=str(APP_DIR / "public"))


# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS Meeting (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                title     TEXT    NOT NULL,
                date      TEXT    NOT NULL,
                createdAt TEXT    NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS Note (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                content   TEXT    NOT NULL,
                meetingId INTEGER NOT NULL REFERENCES Meeting(id) ON DELETE CASCADE,
                createdAt TEXT    NOT NULL DEFAULT (datetime('now'))
            );
        """)


# ── Helpers ───────────────────────────────────────────────────────────────────

def meeting_row_to_dict(row, notes=None):
    d = dict(row)
    d["notes"] = notes if notes is not None else []
    return d


def note_row_to_dict(row):
    return dict(row)


# ── Meetings ──────────────────────────────────────────────────────────────────

@app.get("/api/meetings")
def list_meetings():
    with get_db() as db:
        meetings = db.execute(
            "SELECT * FROM Meeting ORDER BY date ASC, createdAt ASC"
        ).fetchall()
        result = []
        for m in meetings:
            notes = db.execute(
                "SELECT * FROM Note WHERE meetingId = ? ORDER BY createdAt ASC",
                (m["id"],),
            ).fetchall()
            result.append(meeting_row_to_dict(m, [note_row_to_dict(n) for n in notes]))
    return jsonify(result), 200


@app.post("/api/meetings")
def create_meeting():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    date = (data.get("date") or "").strip()
    if not title or not date:
        return jsonify({"error": "title and date are required"}), 400
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO Meeting (title, date) VALUES (?, ?)", (title, date)
        )
        row = db.execute(
            "SELECT * FROM Meeting WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return jsonify(meeting_row_to_dict(row, [])), 201


@app.delete("/api/meetings/<int:meeting_id>")
def delete_meeting(meeting_id):
    with get_db() as db:
        db.execute("DELETE FROM Meeting WHERE id = ?", (meeting_id,))
    return "", 204


# ── Notes ─────────────────────────────────────────────────────────────────────

@app.post("/api/meetings/<int:meeting_id>/notes")
def add_note(meeting_id):
    data = request.get_json(silent=True) or {}
    content = (data.get("content") or "").strip()
    if not content:
        return jsonify({"error": "content is required"}), 400
    with get_db() as db:
        cur = db.execute(
            "INSERT INTO Note (content, meetingId) VALUES (?, ?)", (content, meeting_id)
        )
        row = db.execute(
            "SELECT * FROM Note WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return jsonify(note_row_to_dict(row)), 201


@app.delete("/api/notes/<int:note_id>")
def delete_note(note_id):
    with get_db() as db:
        db.execute("DELETE FROM Note WHERE id = ?", (note_id,))
    return "", 204


# ── Search ────────────────────────────────────────────────────────────────────

@app.get("/api/search")
def search_notes():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify([]), 200
    with get_db() as db:
        notes = db.execute(
            """
            SELECT n.*, m.title AS meeting_title, m.date AS meeting_date
            FROM Note n
            JOIN Meeting m ON n.meetingId = m.id
            WHERE n.content LIKE ? COLLATE NOCASE
            ORDER BY n.createdAt DESC
            """,
            (f"%{q}%",),
        ).fetchall()
    result = []
    for n in notes:
        d = dict(n)
        d["meeting"] = {"title": d.pop("meeting_title"), "date": d.pop("meeting_date")}
        result.append(d)
    return jsonify(result), 200


# ── SPA fallback ──────────────────────────────────────────────────────────────

@app.get("/")
@app.get("/<path:path>")
def serve_spa(path=""):
    pub = app.static_folder
    if path and (Path(pub) / path).is_file():
        return send_from_directory(pub, path)
    return send_from_directory(pub, "index.html")


# ── Boot ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=PORT, debug=False)
