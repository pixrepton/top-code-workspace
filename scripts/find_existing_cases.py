"""Find existing cases in mailbox_memory."""
import psycopg, json
from dotenv import dotenv_values

vals = dotenv_values('/etc/topinstal/gmail-agent.env')
db = vals['MAILBOX_MEMORY_DATABASE_URL']
conn = psycopg.connect(db)
cur = conn.cursor()

cur.execute("""SELECT column_name FROM information_schema.columns WHERE table_name='mailbox_memory_cases'""")
cols = [r[0] for r in cur.fetchall()]
print('Columns:', cols)

cur.execute("""SELECT %s FROM public.mailbox_memory_cases ORDER BY created_at DESC LIMIT 10""" % ', '.join(cols[:8]))
rows = cur.fetchall()
print()
print('Cases:')
for r in rows:
    print('  %s' % str(r)[:400])
conn.close()
