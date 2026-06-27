"""Clean one specific engagement from DB."""
import psycopg
from dotenv import dotenv_values

vals = dotenv_values('/etc/topinstal/gmail-agent.env')
db = vals['MAILBOX_MEMORY_DATABASE_URL']
conn = psycopg.connect(db)
cur = conn.cursor()
eid = 'stg_sig_2cced8e2'
tables = ['agent_runtime_turns', 'operator_engagement_snapshots', 'agent_proposal_records', 'agent_run_checkpoints']
for tbl in tables:
    cur.execute("DELETE FROM public.%s WHERE engagement_id = '%s'" % (tbl, eid))
    print('Cleared %s: %d' % (tbl, cur.rowcount))
conn.commit()
conn.close()
print('Done')
