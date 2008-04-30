#!/bin/env python2.4

print """
record(waveform, "%(device)s:SETI_C") {
  field(NELM, "%(size)d")
  field(FTVL, "DOUBLE")
}

record(waveform, "%(device)s:I_C") {
  field(NELM, "%(size)d")
  field(FTVL, "DOUBLE")
}

record(waveform, "%(device)s:MIN_C") {
  field(NELM, "%(size)d")
  field(FTVL, "DOUBLE")
}

record(waveform, "%(device)s:MAX_C") {
  field(NELM, "%(size)d")
  field(FTVL, "DOUBLE")
}

record(waveform, "%(device)s:I_R") {
  field(NELM, "%(size)d")
  field(FTVL, "DOUBLE")
}

record(waveform, "%(device)s:SETI_R") {
  field(NELM, "%(size)d")
  field(FTVL, "DOUBLE")
}
""" % ({"device": "SR-CS-PC-01", "size": 1000})
