"""Delete all staging engagement data (engagement_id starting with stg_)."""
import psycopg, os
from dotenv import dotenv_values

vals = dotenv_values('/etc/topinstal/gmail-agent.env')
db = vals.get('MAILBOX_MEMORY_DATABASE_URL', '')
if not db:
    print('No DB URL')
    exit(1)

conn = psycopg.connect(db)
cur = conn.cursor()
tables = ['agent_runtime_turns', 'operator_engagement_snapshots', 'agent_proposal_records', 'agent_run_checkpoints']
total = 0
for tbl in tables:
    sql = "DELETE FROM public.%s WHERE engagement_id LIKE 'stg_%%'" % tbl
    cur.execute(sql)
    n = cur.rowcount
    total += n
    print('Cleared %s: %d rows' % (tbl, n))
conn.commit()
conn.close()
print('Total: %d rows' % total)
