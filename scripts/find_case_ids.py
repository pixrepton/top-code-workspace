"""Find case_ids for SCENARIO 2."""
import psycopg
from dotenv import dotenv_values

vals = dotenv_values('/etc/topinstal/gmail-agent.env')
db = vals['MAILBOX_MEMORY_DATABASE_URL']
conn = psycopg.connect(db)
cur = conn.cursor()

cur.execute("""SELECT case_id, customer_email, subject, status FROM public.mailbox_memory_cases ORDER BY created_at DESC LIMIT 10""")
for r in cur.fetchall():
    print('  %s: email=%-30s status=%-12s subject=%s' % (r[0][:24] if r[0] else 'N/A', r[1] or '-', r[2] or '-', (r[3] or '-')[:40]))

conn.close()
