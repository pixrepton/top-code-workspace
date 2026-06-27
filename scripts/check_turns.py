"""Check latest agent turns for error details."""
import psycopg, json, os, sys
from dotenv import dotenv_values

env_path = "/etc/topinstal/gmail-agent.env"
if os.path.isfile(env_path):
    values = dotenv_values(env_path)
else:
    print("No env file")
    sys.exit(1)

db_url = values.get("MAILBOX_MEMORY_DATABASE_URL", "")
if not db_url:
    print("No DB URL")
    sys.exit(1)

conn = psycopg.connect(db_url)
cur = conn.cursor()

# Check columns
cur.execute("""
    SELECT column_name FROM information_schema.columns 
    WHERE table_name='agent_runtime_turns'
""")
cols = [r[0] for r in cur.fetchall()]
print("Columns:", cols)

# Get latest 5 turns with all data
col_names = ", ".join(cols[:15])
cur.execute("""
    SELECT %s FROM public.agent_runtime_turns
    ORDER BY created_at DESC LIMIT 10
""" % col_names)
rows = cur.fetchall()
print()
print("=== Latest turns ===")
for row in rows:
    eid_idx = 0  # engagement_id
    tool_idx = cols.index('tool_name') if 'tool_name' in cols else -1
    status_idx = cols.index('tool_status') if 'tool_status' in cols else -1
    summary_idx = cols.index('turn_summary_pl') if 'turn_summary_pl' in cols else -1
    args_idx = cols.index('tool_args_redacted') if 'tool_args_redacted' in cols else -1
    
    print("  eng=%s tool=%s status=%s" % (
        (str(row[eid_idx]) if eid_idx < len(row) else '?')[-30:],
        row[tool_idx] if tool_idx >= 0 else '?',
        row[status_idx] if status_idx >= 0 else '?'
    ))
    if summary_idx >= 0:
        print("    summary: %s" % str(row[summary_idx])[:200])
    if args_idx >= 0 and row[args_idx]:
        print("    args: %s" % str(row[args_idx])[:300])

conn.close()
