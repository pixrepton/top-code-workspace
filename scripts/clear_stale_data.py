"""Clear stale staging data for fresh run."""
import os
from dotenv import dotenv_values
import psycopg

vals = dotenv_values('/etc/topinstal/gmail-agent.env')
db = vals.get('MAILBOX_MEMORY_DATABASE_URL', '')

if db:
    conn = psycopg.connect(db)
    cur = conn.cursor()
    tables = ['agent_runtime_turns', 'operator_engagement_snapshots', 'agent_proposal_records', 'agent_run_checkpoints', 'operator_response_records']
    for tbl in tables:
        sql = "DELETE FROM public.%s WHERE engagement_id LIKE 'stg_%%'" % tbl
        cur.execute(sql)
        cnt = cur.rowcount
        print('Cleared %s: %d rows' % (tbl, cnt))
    conn.commit()
    conn.close()
    print('Done')
else:
    print('No DB URL')
