"""Check agent turns for latest engagement."""
import psycopg, json
from dotenv import dotenv_values

vals = dotenv_values('/etc/topinstal/gmail-agent.env')
db = vals['MAILBOX_MEMORY_DATABASE_URL']
conn = psycopg.connect(db)
cur = conn.cursor()

cur.execute("""SELECT engagement_id, turn_id, tool_name, tool_status, turn_summary_pl, tokens_used, snapshot_version
FROM public.agent_runtime_turns
WHERE engagement_id LIKE 'stg_sig_7fe3f0c5%%'
ORDER BY turn_id""")
rows = cur.fetchall()
print('Turns for stg_sig_7fe3f0c5:')
for r in rows:
    print('  %s: tool=%-30s status=%-10s ver=%-3s tokens=%-6s %s' % (
        (r[1] or '')[-16:], r[2] or '-', r[3] or '-', r[6] if len(r)>6 else '?',
        str(r[5] or '-'), (r[4] or '')[:150]
    ))

conn.close()
