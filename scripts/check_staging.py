"""Check agent turns for latest engagements."""
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

# First check agent_runtime_turns columns
cur.execute("""
    SELECT column_name FROM information_schema.columns 
    WHERE table_name='agent_runtime_turns'
""")
cols = [r[0] for r in cur.fetchall()]
print("agent_runtime_turns columns:", cols)

# Show latest agent turns
cur.execute("""
    SELECT engagement_id, turn_id, tool_name, tool_status, turn_summary_pl
    FROM public.agent_runtime_turns
    ORDER BY created_at DESC LIMIT 15
""")
print()
print("=== Latest agent turns ===")
for row in cur.fetchall():
    eid, idx, tool, status, summary = row
    print("  %s turn=%s tool=%-35s status=%-8s summary=%s" % (
        (eid or "")[-20:], idx or 0, tool or "-", status or "-", (summary or "")[:120]
    ))

# Show latest proposals
cur.execute("""
    SELECT column_name FROM information_schema.columns 
    WHERE table_name='agent_proposal_records'
""")
pcols = [r[0] for r in cur.fetchall()]
print()
print("agent_proposal_records columns:", pcols)

cur.execute("""
    SELECT engagement_id, proposal_type, proposal_state, created_at
    FROM public.agent_proposal_records
    ORDER BY created_at DESC LIMIT 5
""")
print()
print("=== Latest proposals ===")
for row in cur.fetchall():
    eid, ptype, state, created = row
    print("  %s type=%-25s state=%-12s %s" % ((eid or "")[-20:], ptype or "-", state or "-", str(created or "")[:19]))

# Show operator_engagement_snapshots columns
cur.execute("""
    SELECT column_name FROM information_schema.columns 
    WHERE table_name='operator_engagement_snapshots'
""")
ecols = [r[0] for r in cur.fetchall()]
print()
print("operator_engagement_snapshots columns:", ecols)

# Get engagement list ordered by created_at
cur.execute("""
    SELECT engagement_id FROM public.operator_engagement_snapshots
    ORDER BY created_at DESC LIMIT 10
""")
engagements = [r[0] for r in cur.fetchall()]
print()
print("=== Latest engagements ===")
for eid in engagements:
    cur.execute("""
        SELECT snapshot_json FROM public.operator_engagement_snapshots
        WHERE engagement_id = %s
        ORDER BY created_at DESC LIMIT 1
    """, (eid,))
    for row in cur.fetchall():
        snap_json = row[0]
        snap = json.loads(snap_json) if isinstance(snap_json, str) else snap_json
        ops = snap.get("operational_status", {})
        hitl = snap.get("hitl_gate", {})
        mem = snap.get("agent_memory", {})
        trace = mem.get("reasoning_trace", []) if mem else []
        props = mem.get("materialize_proposals", []) if mem else []
        print("  %s status=%-20s hitl=%s turns=%d proposals=%d" % (
            eid[-20:], ops.get("code", "?"), hitl.get("required", "?"), len(trace), len(props)
        ))
        for t in trace:
            data = t.get("data", t)
            if isinstance(data, dict):
                summary = data.get("turn_summary_pl", data.get("summary_pl", str(data)[:100]))
            else:
                summary = str(data)[:100]
            print("    Turn: %s" % summary[:150])

conn.close()
