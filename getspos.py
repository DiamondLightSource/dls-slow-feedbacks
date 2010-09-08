#!/usr/bin/env dls-python2.6

import dls1225
from numpy import *

def getspos():
    # positions at the end of the element
    pos = []
    names = ["START"]
    s = 0
    for r in dls1225.RING:
        pos.append(s)
        s += dls1225.families[r].L
        names.append(r)
    pos.append(s)
    return (array(names), array(pos))

if __name__ == "__main__":
    (names, pos) = getspos()
    print pos[names == "BPM"]
    print pos[names == "HSTR"]
    print pos[names == "VSTR"]
    
    # build these into position vectors
    # what about the simulator?
    
    

    



