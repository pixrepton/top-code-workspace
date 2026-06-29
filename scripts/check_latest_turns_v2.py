"""Check latest agent turns from DB."""
import psycopg, json
from dotenv import dotenv_values

vals = dotenv_values('/etc/topinstal/gmail-agent.env')
db = vals['MAILBOX_MEMORY_DATABASE_URL']
conn = psycopg.connect(db)
cur = conn.cursor()

cur.execute("""SELECT engagement_id FROM public.agent_runtime_turns ORDER BY created_at DESC LIMIT 1""")
latest = cur.fetchone()
if latest:
    eid = latest[0]
    print('Latest engagement:', eid)
    cur.execute("""SELECT turn_id, tool_name, tool_status, turn_summary_pl FROM public.agent_runtime_turns WHERE engagement_id = %s ORDER BY turn_id""", (eid,))
    rows = cur.fetchall()
    for r in rows:
        print('  %s: tool=%-35s status=%-10s %s' % (r[0][-16:], r[1] or '-', r[2] or '-', (r[3] or '')[:200]))

    cur.execute("""SELECT proposal_id, proposal_type FROM public.agent_proposal_records WHERE engagement_id = %s ORDER BY created_at DESC""", (eid,))
    pra = cur.fetchall()
    print('Proposals:', len(pra))
    for r in pra:
        print('  %s: %s' % (r[0][:24], r[1]))
conn.close()
