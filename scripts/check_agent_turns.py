"""Check agent turn journal in Postgres."""
import psycopg
import json
import os

db_url = os.environ.get("MAILBOX_MEMORY_DATABASE_URL", "") or ""

if not db_url:
    from dotenv import dotenv_values
    values = dotenv_values("/etc/topinstal/gmail-agent.env")
    db_url = values.get("MAILBOX_MEMORY_DATABASE_URL", "")

print("DB URL found:", bool(db_url))

if db_url:
    conn = psycopg.connect(db_url)
    cur = conn.cursor()

    # List all tables
    cur.execute("""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema IN ('public', 'agent_runtime')
        ORDER BY table_schema, table_name
    """)
    tables = [(r[0], r[1]) for r in cur.fetchall()]
    print("Tables:")
    for schema, tbl in tables:
        print("  %s.%s" % (schema, tbl))

    # Check operator_engagements and turn_journal
    for schema, tbl in tables:
        try:
            cur.execute('SELECT COUNT(*) FROM %s.%s' % (schema, tbl))
            cnt = cur.fetchone()[0]
            print("  %s.%s: %d rows" % (schema, tbl, cnt))

            # Show sample data for small tables
            if cnt > 0 and cnt < 20:
                col_q = "SELECT column_name FROM information_schema.columns WHERE table_schema='%s' AND table_name='%s'" % (schema, tbl)
                cur.execute(col_q)
                cols = [r[0] for r in cur.fetchall()]
                cur.execute('SELECT * FROM %s.%s LIMIT 3' % (schema, tbl))
                for row in cur.fetchall():
                    print("    Row: %s" % str(row)[:300])
        except Exception as e:
            print("  %s.%s: ERROR - %s" % (schema, tbl, e))

    conn.close()
