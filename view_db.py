"""
Rail Nirdeshak - SQLite Database Quick Inspector
Run this script to inspect database tables and live rows in a clean formatted view:
    python view_db.py
Or inspect a specific table:
    python view_db.py trains
    python view_db.py etas
    python view_db.py observations
    python view_db.py stations
    python view_db.py users
"""

import sqlite3
import os
import sys

DB_PATH = os.path.join(os.path.dirname(__file__), "rail_nirdeshak.db")

def print_header(title):
    print("\n" + "=" * 80)
    print(f"  {title.upper()}")
    print("=" * 80)

def print_table(headers, rows):
    if not rows:
        print("  (No records found)")
        return
    # Determine column widths
    col_widths = [len(h) for h in headers]
    str_rows = []
    for r in rows:
        row_strs = [str(val if val is not None else "") for val in r]
        str_rows.append(row_strs)
        for i, val in enumerate(row_strs):
            if len(val) > col_widths[i]:
                col_widths[i] = min(35, len(val)) # cap at 35 chars

    fmt = " | ".join(f"{{:<{w}}}" for w in col_widths)
    separator = "-+-".join("-" * w for w in col_widths)

    print(fmt.format(*headers))
    print(separator)
    for r in str_rows:
        truncated = [val[:32] + "..." if len(val) > 35 else val for val in r]
        print(fmt.format(*truncated))
    print(f"Total records: {len(rows)}\n")

def show_summary(conn):
    print_header("Rail Nirdeshak - Database Overview (rail_nirdeshak.db)")
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
    tables = [t[0] for t in cursor.fetchall()]
    
    summary_rows = []
    for t in tables:
        cursor.execute(f"SELECT COUNT(*) FROM \"{t}\";")
        cnt = cursor.fetchone()[0]
        cursor.execute(f"PRAGMA table_info(\"{t}\");")
        cols = [c[1] for c in cursor.fetchall()]
        summary_rows.append([t, cnt, ", ".join(cols[:4]) + ("..." if len(cols) > 4 else "")])
    
    print_table(["Table Name", "Row Count", "Key Columns"], summary_rows)

def show_trains(conn):
    print_header("1. Active Trains & Live Telemetry")
    cursor = conn.cursor()
    query = """
    SELECT 
        t.train_number, 
        t.train_name, 
        t.source, 
        t.destination, 
        l.speed_kmh, 
        l.current_delay_min, 
        l.status, 
        l.track_section,
        l.reference_pole
    FROM trains t
    LEFT JOIN live_train_states l ON t.id = l.train_id;
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    print_table(
        ["Train No.", "Name", "Source", "Destination", "Speed (km/h)", "Delay (min)", "Status", "Track Section", "Pole"],
        rows
    )

def show_etas(conn):
    print_header("2. Dynamic ETA Predictions & Delay Breakdown")
    cursor = conn.cursor()
    query = """
    SELECT 
        t.train_number,
        s.code,
        s.name,
        e.scheduled_arrival,
        e.predicted_arrival,
        e.predicted_delay_min,
        e.propagation_risk,
        e.reason_summary
    FROM eta_predictions e
    JOIN trains t ON e.train_id = t.id
    JOIN stations s ON e.station_id = s.id
    ORDER BY t.train_number, e.id;
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    print_table(
        ["Train", "Station", "Station Name", "Sched", "Pred", "Delay(m)", "Prop. Risk", "Reason Breakdown"],
        rows
    )

def show_observations(conn):
    print_header("3. Field Survey & Track Observations")
    cursor = conn.cursor()
    query = """
    SELECT 
        f.id,
        f.track_section,
        f.pole_reference,
        f.observation_type,
        f.impact_delay_min,
        f.severity,
        f.description
    FROM field_observations f;
    """
    cursor.execute(query)
    rows = cursor.fetchall()
    print_table(
        ["ID", "Section", "Pole Ref", "Type", "Impact (+m)", "Severity", "Description"],
        rows
    )

def show_stations(conn):
    print_header("4. Corridor Stations")
    cursor = conn.cursor()
    query = "SELECT code, name, zone, division, latitude, longitude FROM stations LIMIT 15;"
    cursor.execute(query)
    rows = cursor.fetchall()
    print_table(["Code", "Station Name", "Zone", "Div", "Latitude", "Longitude"], rows)

def show_users(conn):
    print_header("5. Registered Users")
    cursor = conn.cursor()
    query = "SELECT id, email, full_name, role FROM users;"
    cursor.execute(query)
    rows = cursor.fetchall()
    print_table(["ID", "Email", "Full Name", "Role"], rows)

def main():
    if not os.path.exists(DB_PATH):
        print(f"Error: Database file not found at {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    arg = sys.argv[1].lower() if len(sys.argv) > 1 else "all"

    if arg in ["summary", "overview"]:
        show_summary(conn)
    elif arg in ["trains", "live"]:
        show_trains(conn)
    elif arg in ["etas", "predictions"]:
        show_etas(conn)
    elif arg in ["observations", "field", "alerts"]:
        show_observations(conn)
    elif arg in ["stations"]:
        show_stations(conn)
    elif arg in ["users"]:
        show_users(conn)
    else:
        show_summary(conn)
        show_trains(conn)
        show_etas(conn)
        show_observations(conn)
        show_users(conn)
        print("Tip: Run 'python view_db.py <table_name>' to view a specific table.")
        print("Examples: python view_db.py trains | etas | observations | stations | users")

    conn.close()

if __name__ == "__main__":
    main()

