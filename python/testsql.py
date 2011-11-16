#!/usr/bin/env dls-python2.6

import sqlite3

conn = sqlite3.connect(":memory:")
conn.text_factory = str

query = "INSERT INTO devices VALUES(?,?,?,?,0,?,?,?)"

def sqlfix2():

    for line in file("mml.sql"):
        conn.execute(line.strip())

    for line in file("hello.txt"):
        (fam, idx, s) = line.split()
        conn.execute(
            "update devices set s=? where family = ? and idx = ?",
            (s, fam, idx))

    for line in conn.iterdump():
        print line

def sqlfix():

    "insert I09 devices"

    for line in file("mml.sql"):
        conn.execute(line.strip())

    # get insertion location
    (loc,) = conn.execute(
        "select idx from devices where devices='SR09A-PC-HSTR-01'").fetchone()

    # add space for new bpms
    conn.execute("update devices set idx=idx+2 where idx >= ?", (loc,))

    spos = 0
    for n in range(2):
        device = "SR09S-PC-HSTR-%02d" % (n + 1)
        conn.execute(query,
            ("hcm", loc + n, device + ":SETI", device + ":I",
             1.8e-5, spos, device))
        device = "SR09S-PC-VSTR-%02d" % (n + 1)
        conn.execute(query,
            ("vcm", loc + n, device + ":SETI", device + ":I",
             1.8e-5, spos, device))
        device = "SR09S-DI-EBPM-%02d" % (n + 1)
        readback = "SR-DI-EBPM-01:SA:X"
        conn.execute(query,
            ("bpmx", loc + n, readback, readback, 1e-3, spos, device))
        readback = "SR-DI-EBPM-01:SA:Y"
        conn.execute(query,
            ("bpmy", loc + n, readback, readback, 1e-3, spos, device))

##    cur = conn.execute("select * from devices order by family, idx")

##     import csv, sys
##     writer = csv.writer(sys.stdout)
##     for line in cur.fetchall():
##         writer.writerow(line)

    for line in conn.iterdump():
        print line

if __name__ == "__main__":
    sqlfix2()
