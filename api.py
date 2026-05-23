"""
TX Lottery Analytics API
========================
FastAPI backend that serves tx_lottery SQL Server data to the Vite React frontend.

Run:  uvicorn api:app --reload --port 8000
"""

import os
from collections import defaultdict

import pyodbc
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="TX Lottery Analytics")

_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
)

_DB_CFG = {
    "driver":   "{ODBC Driver 17 for SQL Server}",
    "server":   os.getenv("TXLOTTERY_SERVER", "jtdc-sqlsrvr.cmhhlofylcq6.us-east-1.rds.amazonaws.com"),
    "database": os.getenv("TXLOTTERY_DB",     "tx_lottery"),
    "uid":      os.getenv("TXLOTTERY_UID",     "tx_lottery_svc"),
    "pwd":      os.getenv("TXLOTTERY_PWD",     ""),
}


def get_db():
    pwd_escaped = _DB_CFG["pwd"].replace("}", "}}")
    cs = (
        f"DRIVER={_DB_CFG['driver']};"
        f"SERVER={_DB_CFG['server']};"
        f"DATABASE={_DB_CFG['database']};"
        f"UID={_DB_CFG['uid']};"
        f"PWD={{{pwd_escaped}}};"
        f"Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=30;"
    )
    return pyodbc.connect(cs)


def _rows_as_dicts(cursor) -> list[dict]:
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def build_snapshot(conn, snapshot_date: str) -> dict:
    cur = conn.execute(
        "SELECT * FROM games_analysis WHERE snapshot_date=? "
        "ORDER BY CASE WHEN adj_prof_score IS NULL THEN 1 ELSE 0 END, adj_prof_score DESC",
        (snapshot_date,),
    )
    games = _rows_as_dicts(cur)
    if not games:
        return None

    cur2 = conn.execute(
        "SELECT * FROM prize_levels WHERE snapshot_date=?", (snapshot_date,)
    )
    levels_by_game: dict[int, list] = defaultdict(list)
    for d in _rows_as_dicts(cur2):
        levels_by_game[d["game_number"]].append({
            "amount":       d["prize_amount"],
            "total":        d["total_printed"],
            "claimed":      d["claimed"],
            "remaining":    d["remaining"],
            "retention":    d["retention_rate"],
            "one_in":       d.get("one_in"),
            "tier":         d.get("tier"),
            "is_meaningful":bool(d.get("is_meaningful")),
            "is_jackpot":   bool(d.get("is_jackpot")),
            "deviation":    d.get("deviation"),
        })

    score_max = None
    for game in games:
        pls = sorted(levels_by_game.get(game["game_number"], []), key=lambda p: p["amount"])
        game["prize_levels"] = pls
        s = game.get("adj_prof_score")
        if s is not None and (score_max is None or s > score_max):
            score_max = s

    cur3 = conn.execute(
        "SELECT DISTINCT snapshot_date FROM games_analysis ORDER BY snapshot_date DESC"
    )
    snapshots = [r[0] for r in cur3.fetchall()]

    return {
        "asOf":      snapshot_date,
        "gameCount": len(games),
        "score_max": score_max,
        "snapshots": snapshots,
        "games":     games,
    }


@app.get("/api/latest")
def get_latest():
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT TOP 1 snapshot_date FROM games_analysis ORDER BY snapshot_date DESC"
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No data in database yet")
        result = build_snapshot(conn, row[0])
        return result
    finally:
        conn.close()


@app.get("/api/snapshot/{snapshot_date}")
def get_snapshot(snapshot_date: str):
    conn = get_db()
    try:
        result = build_snapshot(conn, snapshot_date)
        if result is None:
            raise HTTPException(status_code=404, detail=f"No data for {snapshot_date}")
        return result
    finally:
        conn.close()


@app.get("/api/snapshots")
def list_snapshots():
    conn = get_db()
    try:
        cur = conn.execute(
            "SELECT snapshot_date, COUNT(*) AS game_count "
            "FROM games_analysis GROUP BY snapshot_date ORDER BY snapshot_date DESC"
        )
        return {"snapshots": [{"date": r[0], "gameCount": r[1]} for r in cur.fetchall()]}
    finally:
        conn.close()
