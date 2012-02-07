#!/usr/bin/env dls-python2.6

"load accelerator object from SQL"
import sqlite3
conn = sqlite3.connect(":memory:")
conn.text_factory = str
mml_sql = "mml.sql"
for line in file(mml_sql).readlines():
    conn.execute(line.strip())

c = conn.cursor()
c.execute("select * from devices order by family, idx")
for row in c.fetchall():
    print ",".join(["%s" % c for c in row])
    
    




