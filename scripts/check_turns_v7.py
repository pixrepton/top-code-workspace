"""Check agent turns."""
import psycopg, json
from dotenv import dotenv_values

vals = dotenv_values('/etc/topinstal/gmail-agent.env')
db = vals['MAILBOX_MEMORY_DATABASE_URL']
conn = psycopg.connect(db)
cur = conn.cursor()

cur.execute("""SELECT turn_id, tool_name, tool_status, turn_summary_pl, tokens_used, snapshot_version
FROM public.agent_runtime_turns
WHERE engagement_id LIKE 'stg_sig_8908735e%%'
ORDER BY turn_id""")
rows = cur.fetchall()
print('Turns:')
for r in rows:
    print('  %s: tool=%-35s status=%-10s ver=%-3s tok=%-6s %s' % (
        (r[0] or '')[-16:], r[1] or '-', r[2] or '-', r[5] if len(r)>5 else '?',
        str(r[4] or '-'), (r[3] or '')[:200]
    ))

conn.close()
