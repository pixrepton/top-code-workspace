"""Check latest agent turns."""
import psycopg
from dotenv import dotenv_values
import json

vals = dotenv_values('/etc/topinstal/gmail-agent.env')
db = vals['MAILBOX_MEMORY_DATABASE_URL']
conn = psycopg.connect(db)
cur = conn.cursor()

cur.execute("""SELECT engagement_id, turn_id, tool_name, tool_status, turn_summary_pl, tokens_used
FROM public.agent_runtime_turns
WHERE engagement_id LIKE 'stg_sig_53ba9aab%%'
ORDER BY turn_id""")
rows = cur.fetchall()
print('Turns for stg_sig_53ba9aab:')
for r in rows:
    print('  %s: tool=%-30s status=%-8s tokens=%-6s %s' % (
        r[1][-16:], r[2] or '-', r[3] or '-', str(r[5] or '-'),
        (r[4] or '')[:120]
    ))

cur.execute("""SELECT proposal_id, proposal_type, proposal_content_json, proposal_reasoning_pl
FROM public.agent_proposal_records
WHERE engagement_id LIKE 'stg_sig_53ba9aab%%'
ORDER BY created_at DESC""")
prows = cur.fetchall()
print()
print('Proposals: %d' % len(prows))
for r in prows:
    print('  %s type=%s' % (r[0][:24], r[1]))
    print('    content: %s' % str(r[2])[:300])
    print('    reasoning: %s' % (r[3] or '')[:200])

conn.close()
