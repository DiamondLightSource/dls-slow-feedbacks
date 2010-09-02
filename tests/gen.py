#!/usr/bin/env python

# generate test harness for the RFFB application

import sys

def correctors(randomize = False):
    import random
    random.seed(1)

    if randomize:
        f = file("random.txt", "w")
    else:
        vs = file("random.txt").readlines()
        f = False
        
    n = 0
    names = []
    for io in range(2):
        end = ["I", "SETI"][io]
        for p in "HV":
            for c in range(24):
                for i in range(7):
                    name = "SR%02dA-PC-%sSTR-%02d:%s" % (c + 1, p, i + 1, end)
                    if randomize:
                        print >> f, (2 * random.random() - 1)
                    else:
                        names.append((name, vs[n].strip()))
                    n += 1
    if f:
        f.close()
    return names

def rf():
    return [("LI-RF-MOSC-01:FREQ", 4.99654e8),
            ("LI-RF-MOSC-01:FREQ_SET", 4.99654e8),
            ("CS-CS-MSTAT-01:FBSTAT", 1),
            ("SR21C-DI-DCCT-01:SIGNAL", 150)]

def concentrator():
    return "SR-DI-EBPM-01:ENABLED"

def vector(x, nelem):
    return '''record(waveform, "%s") {
    field(NELM, "%s")
    field(FTVL, "DOUBLE")
    field(SCAN, "1 second")
    }''' % (x, nelem)

def record(x, val):
    return 'record(ai, "%s") { field(SCAN, "1 second") field(VAL, "%s") }' % (x, val)

def main():
    
    for c in correctors():
        print record(*c)

    for r in rf():
        print record(*r)

    print vector(concentrator(), 170)

def randomize():
    import random

    f = file("random.txt", "w")
    print >> f, (2 * random.random() - 1)
    f.close()

if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "randomize":
        correctors(randomize = True)
    else:
        main()        



