#!/usr/bin/env dls-python2.6

"MML for RFFB and SOFB"

from numpy import *

def many(xs, i):
    return array([x + i for x in xs])

class family(object):
    def __init__(self, **kw):
        for (k, v) in kw.items():
            setattr(self, k, v)

def make_families():

    # [rad A^-1] values from middlelayer

    v_rad_over_A = [
        0.212712745518659,
        0.212712745518659,
        0.154932744696152,
        0.212712745518659,
        0.155312481816268,
        0.212712745518659,
        0.212712745518659] * 24
    
    h_rad_over_A = [
        0.219088331921733,
        0.219088331921733,
        0.163286961340012,
        0.219088331921733,
        0.161008538618683,
        0.219088331921733,
        0.219088331921733] * 24

    # add 13S correctors and scale correctly
    h_rad_over_A = array(h_rad_over_A[:12*7] + [1, 1] + h_rad_over_A[12*7:]) * 1e-3
    v_rad_over_A = array(v_rad_over_A[:12*7] + [1, 1] + v_rad_over_A[12*7:]) * 1e-3
    
    cm = [None, None]
    
    for p in range(2):
        correctors = ["SR%02dA-PC-%sSTR-%02d" % (c + 1, "HV"[p], i + 1)
                      for c in range(24) for i in range(7)]
        
        cell13 = ["SR13S-PC-%sSTR-%02d" % ("HV"[p], i+1) for i in range(2)]
        
        correctors = array(correctors[:12*7] + cell13 + correctors[12*7:])
        cm[p] = correctors

    # boolean indexing for enable
    h_enabled_cor = array([True] * len(cm[0]))
    v_enabled_cor = array([True] * len(cm[1]))
    NBPMS = 170
    enabled_bpm = array([True] * NBPMS)

    ao = {"hcm": family(setpoint   = many(cm[0], ":SETI"),
                        readback   = many(cm[0], ":I"),
                        enabled    = h_enabled_cor,
                        hw2physics = h_rad_over_A,
                        devices    = cm[0],
                        access     = "scalar"),
          
          "vcm": family(setpoint   = many(cm[1], ":SETI"),
                        readback   = many(cm[1], ":I"),
                        enabled    = v_enabled_cor,
                        hw2physics = v_rad_over_A,
                        devices    = cm[1],
                        access     = "scalar"),

          "bpmx": family(readback  = "SR-DI-EBPM-01:SA:X",
                         enabled   = enabled_bpm,
                         access    = "vector"),
          
          "bpmy": family(readback  = "SR-DI-EBPM-01:SA:Y",
                         enabled   = enabled_bpm,
                         access    = "vector")
          
          }
    
    return ao

def disable_i13(ao):
    ao["vcm"].enabled[7*12:7*12+2] = False
    ao["hcm"].enabled[7*12:7*12+2] = False
    ao["bpmx"].enabled[7*12:7*12+2] = False
    ao["bpmy"].enabled[7*12:7*12+2] = False

ao = make_families()
disable_i13(ao)

def getrb(fam):
    if fam.access == "vector":
        return array(caget(fam.readback)[fam.enabled])
    else:
        return array(caget(fam.readback[fam.enabled]))
        
if __name__ == "__main__":

    import sys
    from pkg_resources import require
    require("cothread")
    from cothread.catools import *

    caput(ao["hcm"].setpoint, 1)
    caput(ao["vcm"].setpoint, 1)
    
    print getrb(ao["hcm"])
    print getrb(ao["bpmx"])
    
    # ok ready for test server?
    # test server has forward response matrix...
    

    
