"""Delete ALL staging engagements from ALL tables that have engagement_id."""
import psycopg
from dotenv import dotenv_values

vals = dotenv_values('/etc/topinstal/gmail-agent.env')
db = vals['MAILBOX_MEMORY_DATABASE_URL']
conn = psycopg.connect(db)
cur = conn.cursor()

# Find all tables with engagement_id column
cur.execute("""
    SELECT table_name, column_name FROM information_schema.columns 
    WHERE table_schema='public' AND column_name='engagement_id'
""")
tables = [(r[0], r[1]) for r in cur.fetchall()]
print('Tables with engagement_id:', [t[0] for t in tables])

total = 0
for tbl, col in tables:
    try:
        sql = "DELETE FROM public.%s WHERE %s LIKE 'stg_%%%%'" % (tbl, col)
        cur.execute(sql)
        n = cur.rowcount
        if n > 0:
            print('  %s: %d rows' % (tbl, n))
            total += n
    except Exception as e:
        pass
conn.commit()
conn.close()
print('Total: %d rows' % total)
