"""Check agent turns."""
import psycopg, json
from dotenv import dotenv_values

vals = dotenv_values('/etc/topinstal/gmail-agent.env')
db = vals['MAILBOX_MEMORY_DATABASE_URL']
conn = psycopg.connect(db)
cur = conn.cursor()

cur.execute("""SELECT turn_id, tool_name, tool_status, turn_summary_pl, tokens_used, snapshot_version
FROM public.agent_runtime_turns
WHERE engagement_id LIKE 'stg_sig_baae4e73%%'
ORDER BY turn_id""")
rows = cur.fetchall()
print('Turns:')
for r in rows:
    print('  %s: tool=%-30s status=%-10s ver=%-3s tok=%-6s %s' % (
        (r[0] or '')[-16:], r[1] or '-', r[2] or '-', r[5] if len(r)>5 else '?',
        str(r[4] or '-'), (r[3] or '')[:200]
    ))

cur.execute("""SELECT proposal_id, proposal_type, proposal_content_json, proposal_reasoning_pl
FROM public.agent_proposal_records
WHERE engagement_id LIKE 'stg_sig_baae4e73%%'
ORDER BY created_at DESC""")
prows = cur.fetchall()
print('\nProposals: %d' % len(prows))
for r in prows:
    print('  %s type=%s' % (str(r[0])[:24], r[1]))
    print('    content: %s' % str(r[2])[:200])
    print('    reasoning: %s' % (r[3] or '')[:200])

conn.close()
