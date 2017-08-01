"MML for RFFB and SOFB, loaded from SQL config file"

import sys, os
import numpy as np
import sqlite3

mml_sql = os.path.join(os.path.dirname(__file__), "mml.sql")

class family(object):
    def __init__(self, **kw):
        for (k, v) in kw.items():
            setattr(self, k, v)

def fromsql():
    "load accelerator object from SQL"
    conn = sqlite3.connect(":memory:")
    conn.text_factory = str
    for line in file(mml_sql).readlines():
        conn.execute(line.strip())
    # connect SQL to objects, make into arrays
    cols = ["setpoint", "readback", "devices", "enabled", "hw2physics", "s"]
    # can't use SQL parameter for column name
    query = "select %(col)s from devices where family = ? order by idx"
    ao2 = {}
    families = conn.execute(
        "select distinct family from devices order by family").fetchall()
    for (f,) in families:
        fdict = {}
        for c in cols:
            rows = conn.execute(query % {"col": c}, (f,)).fetchall()
            v = np.array([r[0] for r in rows])
            fdict[c] = v
        ao2[f] = family(**fdict)
    # fix up vector channels
    ao2["bpmx"].readback = ao2["bpmx"].readback[0]
    ao2["bpmy"].readback = ao2["bpmy"].readback[0]
    return ao2

ao = fromsql()
