"""
One-time backfill: populate csv_raw for snapshots that pre-date the table.

Strategy:
  - For each snapshot_date in prize_levels that has no csv_raw rows yet,
    reconstruct rows from prize_levels JOIN games_analysis.
  - prize_level is formatted from the float prize_amount (e.g. "1000"),
    not the original CSV string — TOTAL rows are not recoverable.
  - For the LATEST snapshot, also re-fetch the live CSV to get the real
    strings and TOTAL rows (only works if the CSV still shows that date).

Run once from D:/dev/lottery:
    python backfill_csv_raw.py
"""

import csv
import io
import os
import re
import sys
from datetime import datetime

import pyodbc
import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.texaslottery.com/",
}
CSV_URL = "https://www.texaslottery.com/export/sites/lottery/Games/Scratch_Offs/scratchoff.csv"

DDL = """
IF NOT EXISTS (SELECT * FROM sys.objects WHERE object_id=OBJECT_ID(N'csv_raw') AND type=N'U')
CREATE TABLE csv_raw (
    id              INT IDENTITY(1,1) PRIMARY KEY,
    snapshot_date   NVARCHAR(10)  NOT NULL,
    game_number     INT,
    game_name       NVARCHAR(200),
    close_date      NVARCHAR(50),
    ticket_price    FLOAT,
    prize_level     NVARCHAR(100),
    total_prizes    INT,
    prizes_claimed  INT,
    CONSTRAINT UQ_csv_raw UNIQUE (snapshot_date, game_number, prize_level)
)
"""

MERGE = """
MERGE csv_raw AS t
USING (SELECT ? AS snapshot_date, ? AS game_number, ? AS prize_level) AS s
    ON t.snapshot_date=s.snapshot_date
   AND t.game_number=s.game_number
   AND t.prize_level=s.prize_level
WHEN MATCHED THEN UPDATE SET
    game_name=?,close_date=?,ticket_price=?,total_prizes=?,prizes_claimed=?
WHEN NOT MATCHED THEN INSERT
    (snapshot_date,game_number,prize_level,game_name,close_date,ticket_price,total_prizes,prizes_claimed)
    VALUES (?,?,?,?,?,?,?,?);
"""


def connect():
    pwd = os.environ.get("TXLOTTERY_PWD", "")
    pwd_escaped = pwd.replace("}", "}}")
    cs = (
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER={os.environ.get('TXLOTTERY_SERVER','jtdc-sqlsrvr.cmhhlofylcq6.us-east-1.rds.amazonaws.com')};"
        f"DATABASE={os.environ.get('TXLOTTERY_DB','tx_lottery')};"
        f"UID={os.environ.get('TXLOTTERY_UID','tx_lottery_svc')};"
        f"PWD={{{pwd_escaped}}};"
        f"Encrypt=yes;TrustServerCertificate=yes;Connection Timeout=30;"
    )
    conn = pyodbc.connect(cs)
    conn.autocommit = False
    return conn


def fetch_live_csv():
    print("Fetching live CSV from TX Lottery...")
    resp = requests.get(CSV_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    text = resp.text
    lines = text.splitlines()
    m = re.search(r"as of (\d{2}/\d{2}/\d{4})", lines[0])
    snapshot_date = ""
    if m:
        snapshot_date = datetime.strptime(m.group(1), "%m/%d/%Y").date().isoformat()
    reader = csv.DictReader(
        io.StringIO("\n".join(lines[1:])),
        fieldnames=["game_number","game_name","close_date","ticket_price",
                    "prize_level","total_prizes","prizes_claimed"],
    )
    next(reader)
    rows = []
    for r in reader:
        try:
            rows.append({
                "game_number":    int(r["game_number"].strip().strip('"')),
                "game_name":      r["game_name"].strip().strip('"'),
                "close_date":     r["close_date"].strip().strip('"') or None,
                "ticket_price":   float(r["ticket_price"].strip()),
                "prize_level":    r["prize_level"].strip().strip('"'),
                "total_prizes":   int(r["total_prizes"].replace(",","").strip() or 0),
                "prizes_claimed": int(r["prizes_claimed"].replace(",","").strip() or 0),
            })
        except (ValueError, KeyError):
            continue
    print(f"  {len(rows)} rows, snapshot_date={snapshot_date!r}")
    return rows, snapshot_date


def reconstruct_from_db(conn, snapshot_date: str) -> list[dict]:
    """Build csv_raw rows from prize_levels + games_analysis for a past snapshot."""
    cur = conn.cursor()
    cur.execute("""
        SELECT
            pl.game_number,
            ga.game_name,
            ga.close_date,
            ga.ticket_price,
            pl.prize_amount,
            pl.total_printed,
            pl.claimed
        FROM prize_levels pl
        LEFT JOIN games_analysis ga
            ON ga.game_number=pl.game_number
           AND ga.snapshot_date=pl.snapshot_date
        WHERE pl.snapshot_date=?
    """, (snapshot_date,))
    rows = []
    for gnum, gname, close_date, price, amount, total, claimed in cur.fetchall():
        # Format prize_level as integer string if whole number, else float string
        if amount is not None and amount == int(amount):
            prize_level = str(int(amount))
        else:
            prize_level = str(amount)
        rows.append({
            "game_number":    gnum,
            "game_name":      gname,
            "close_date":     close_date,
            "ticket_price":   price,
            "prize_level":    prize_level,
            "total_prizes":   total,
            "prizes_claimed": claimed,
        })
    print(f"  Reconstructed {len(rows)} rows from DB for {snapshot_date}")
    return rows


def insert_rows(conn, rows: list[dict], snapshot_date: str):
    cur = conn.cursor()
    n = 0
    for r in rows:
        cur.execute(MERGE, [
            snapshot_date, r["game_number"], r["prize_level"],
            r["game_name"], r.get("close_date"), r["ticket_price"],
            r["total_prizes"], r["prizes_claimed"],
            snapshot_date, r["game_number"], r["prize_level"],
            r["game_name"], r.get("close_date"), r["ticket_price"],
            r["total_prizes"], r["prizes_claimed"],
        ])
        n += 1
    conn.commit()
    print(f"  Wrote {n} rows for {snapshot_date}")


def main():
    conn = connect()
    cur = conn.cursor()

    # Ensure table exists
    cur.execute(DDL)
    conn.commit()

    # Find all snapshot dates in prize_levels
    cur.execute("SELECT DISTINCT snapshot_date FROM prize_levels ORDER BY snapshot_date")
    all_dates = [r[0] for r in cur.fetchall()]
    print(f"Snapshots found in prize_levels: {all_dates}")

    # Find which already have csv_raw rows
    cur.execute("SELECT DISTINCT snapshot_date FROM csv_raw")
    already_done = {r[0] for r in cur.fetchall()}
    print(f"Already in csv_raw: {sorted(already_done)}")

    missing = [d for d in all_dates if d not in already_done]
    if not missing:
        print("Nothing to backfill.")
        conn.close()
        return

    # Try to get the live CSV — if it matches one of the missing dates, use it for that one
    try:
        live_rows, live_date = fetch_live_csv()
    except Exception as e:
        print(f"  Warning: could not fetch live CSV: {e}")
        live_rows, live_date = [], ""

    for snap in missing:
        print(f"\nBackfilling {snap}...")
        if snap == live_date and live_rows:
            print(f"  Using live CSV (exact match for {snap})")
            insert_rows(conn, live_rows, snap)
        else:
            print(f"  Live CSV is for {live_date!r}, reconstructing {snap} from prize_levels")
            rows = reconstruct_from_db(conn, snap)
            insert_rows(conn, rows, snap)

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
