"""Find specific turn_id in DB."""
import psycopg
from dotenv import dotenv_values

vals = dotenv_values('/etc/topinstal/gmail-agent.env')
db = vals['MAILBOX_MEMORY_DATABASE_URL']
conn = psycopg.connect(db)
cur = conn.cursor()

# Check if the specific turn_id exists
cur.execute("SELECT engagement_id, turn_id FROM public.agent_runtime_turns WHERE turn_id LIKE 'turn_74697be4%%'")
rows = cur.fetchall()
if rows:
    print('Found in agent_runtime_turns:')
    for r in rows:
        print(' ', r)
else:
    print('Not in agent_runtime_turns')

# Check operator_engagement_snapshots for the same engagement
cur.execute("SELECT engagement_id FROM public.operator_engagement_snapshots WHERE engagement_id LIKE '%%2cced8e2%%'")
rows = cur.fetchall()
if rows:
    print('Found in operator_engagement_snapshots:')
    for r in rows:
        print(' ', r)
else:
    print('Not in operator_engagement_snapshots')

# Check if there are sequences that reset
cur.execute("SELECT table_name, column_name FROM information_schema.columns WHERE column_default LIKE '%%turn%%'")
for r in cur.fetchall():
    print('Turn column:', r)

conn.close()
