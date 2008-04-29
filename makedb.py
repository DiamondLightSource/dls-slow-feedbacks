#!/bin/env python2.4

names = open("names.txt").readlines()
names = list(set([n.strip() for n in names if n.find("-PC-") != -1]))

r = """
record(ai, "%(name)s:I_C") {
  field(INP, "%(name)s:I CP")
}
record(ai, "%(name)s:SETI_C") {
  field(INP, "%(name)s:SETI CP")
}
record(ai, "%(name)s:MIN_C") {
  field(INP, "%(name)s:SETI.LOPR CP")
}
record(ai, "%(name)s:MAX_C") {
  field(INP, "%(name)s:SETI.HOPR CP")
}
"""

for n in names:
    print r % {"name": n}

print """
record(waveform, "SR-CS-PC-01:SETI_C") {
  field(NELM, "%(length)d")
  field(FTVL, "DOUBLE")
}
record(waveform, "SR-CS-PC-01:I_C") {
  field(NELM, "%(length)d")
  field(FTVL, "DOUBLE")
}
record(waveform, "SR-CS-PC-01:MIN_C") {
  field(NELM, "%(length)d")
  field(FTVL, "DOUBLE")
}
record(waveform, "SR-CS-PC-01:MAX_C") {
  field(NELM, "%(length)d")
  field(FTVL, "DOUBLE")
}
record(waveform, "SR-CS-PC-01:I_R") {
  field(NELM, "%(length)d")
  field(FTVL, "DOUBLE")
}
record(waveform, "SR-CS-PC-01:SETI_R") {
  field(NELM, "%(length)d")
  field(FTVL, "DOUBLE")
}
""" % {"length": len(names)}
