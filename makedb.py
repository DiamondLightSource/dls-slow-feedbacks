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
record(waveform, "SETI_C") {
  field(NELM, "%(length)d")
  field(FTVL, "DOUBLE")
}
record(waveform, "I_C") {
  field(NELM, "%(length)d")
  field(FTVL, "DOUBLE")
}
record(waveform, "MIN_C") {
  field(NELM, "%(length)d")
  field(FTVL, "DOUBLE")
}
record(waveform, "MAX_C") {
  field(NELM, "%(length)d")
  field(FTVL, "DOUBLE")
}
record(waveform, "I_PERCENT") {
  field(NELM, "%(length)d")
  field(FTVL, "DOUBLE")
}
record(waveform, "SETI_PERCENT") {
  field(NELM, "%(length)d")
  field(FTVL, "DOUBLE")
}
""" % {"length": len(names)}
