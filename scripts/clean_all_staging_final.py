"""Delete ALL stale staging data from ALL tables."""
import psycopg
from dotenv import dotenv_values

vals = dotenv_values('/etc/topinstal/gmail-agent.env')
conn = psycopg.connect(vals['MAILBOX_MEMORY_DATABASE_URL'])
cur = conn.cursor()

tables = [
    'agent_runtime_turns', 'operator_engagement_snapshots',
    'agent_proposal_records', 'agent_run_checkpoints',
    'unified_os_events', 'correlation_links', 'topinstal_engagements',
    'mailbox_memory_signals', 'mailbox_memory_signal_processing_attempts'
]

total = 0
for t in tables:
    try:
        sql = "DELETE FROM public.%s WHERE engagement_id LIKE 'stg_%s'" % (t, '%')
        cur.execute(sql)
        n = cur.rowcount
        if n > 0:
            total += n
            print('%s: %d' % (t, n))
    except Exception as e:
        pass

conn.commit()
conn.close()
print('Total: %d' % total)
