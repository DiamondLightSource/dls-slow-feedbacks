#!/usr/bin/env dls-python2.6

import sys, os
from pkg_resources import require
require('cothread==1.16')
require('scipy==0.8.0b1')
from scipy.io.matlab import *
from numpy import *
from numpy.linalg import svd, pinv
from cothread.catools import *

cache = {}

def get_dispcor(enabled_bpm, enabled_cor, bpmresp, disp, rad_over_A):
    "get the dispersion corrector vector and cache"
    
    # pad out the 13S bpms
    xr = range(170)
    xr.remove(12*7+0)
    xr.remove(12*7+1)
    
    key = (tuple(enabled_bpm), tuple(enabled_cor))
    if key in cache:
        return cache[key]
    
    dispx = disp["BPMxDisp"]["Data"][0,0]
    rmx = bpmresp["Rmat"][0,0]["Data"]
    
    # disable bpms
    dispx = dispx[enabled_bpm]
    rmx = rmx[ix_(enabled_bpm, enabled_cor)] / rad_over_A[enabled_cor]
    
    dispcor = dot(pinv(rmx), dispx)
    cache[key] = dispcor
    return dispcor

def calc_rffb(bpmresp, disp, enabled_bpm, enabled_cor, hcm, rad_over_A):
    "calculate the RF change"
    dispcor = get_dispcor(enabled_bpm, enabled_cor, bpmresp, disp, rad_over_A)
    # the "inverse" of a vector v is: v / |v|^2
    # same as you get from the svd pinv:
    # pinv([v])[0] = v / sum(v**2)
    drf = dot(hcm * rad_over_A[enabled_cor], dispcor / sum(dispcor**2))
    return drf

def test_subset(badbpm, mdrf, hcm, bpmresp, disp, rad_over_A):
    CLIGHT = 299792458
    CIRCUMFERENCE = 561.6
    BUCKETS = 936
    ALPHA = 1.701116728953387e-4
    RFFREQ = 4.996540966666673e8
    MCF = 1.700945275305007e-4
    SF = 1.0 / BUCKETS * CIRCUMFERENCE / CLIGHT / ALPHA
    SCALE = SF * MCF * RFFREQ
    enabled_cor = range(170)
    enabled_cor.remove(7*12+0)
    enabled_cor.remove(7*12+1)
    enabled_bpm = range(170)
    for n in badbpm:
        enabled_bpm[n-1] = 0
    
    drf = calc_rffb(bpmresp, disp, enabled_bpm, enabled_cor, hcm, rad_over_A)
    # scale difference because Matlab uses two MCF values
    drf2 = drf / SCALE
    diff = drf2 - mdrf
    if abs(diff) > 1e-7:
        result = "\033[31;1mTEST FAIL\033[0m"
    else:
        result = "\033[32;1mTEST OK  \033[0m"
    print "%s: matlab %g python %g diff %g" % (result, mdrf, drf2, diff)

def test_online(bpmresp, disp, rad_over_A):
    correctors = ["SR%02dA-PC-HSTR-%02d:I" % (c + 1, i + 1)
                  for c in range(24) for i in range(7)]

    cell13 = ["SR13S-PC-HSTR-01", "SR13S-PC-HSTR-02"]
    correctors = correctors[:7*12] + cell13 + correctors[7*12:]
    # print correctors
    enabled_cor = range(170)
    enabled_cor.remove(7*12+0)
    enabled_cor.remove(7*12+1)
    # get without trying to connect to disabled correctors
    hcm = array(caget(array(correctors)[enabled_cor]))
    enabled_bpm = nonzero(caget("SR-DI-EBPM-01:ENABLED") == 0)[0]
    # enabled_bpm = range(168)
    drf = calc_rffb(bpmresp, disp, enabled_bpm, enabled_cor, hcm, rad_over_A)
    print "delta rf", drf

def run_tests():
    
    dirname = "/home/diamond/common/matlab/middlelayer/2-0/machine/diamondopsdata/SR"
    bpmresp = loadmat(os.path.join(dirname, "GoldenBPMResp"))
    disp = loadmat(os.path.join(dirname, "GoldenDisp"))
    assert(bpmresp["Rmat"][0,0]["Units"] == "Hardware")
    assert(disp["BPMxDisp"]["Units"] == "Hardware")

    rad_over_A = [
        0.219088331921733,
        0.219088331921733,
        0.163286961340012,
        0.219088331921733,
        0.161008538618683,
        0.219088331921733,
        0.219088331921733] * 24

    # add 13S correctors
    rad_over_A = array(rad_over_A[:12*7] + [1, 1] + rad_over_A[12*7:]) * 1e-3
    
    # randomized correctors
    hcm = [-0.73127151177500005, 0.69486747387400005, 0.52754923795300002, -0.48986194852100001, -0.0091298258161200008, -0.10101787042300001, 0.30318594544600003, 0.57744670227100003, -0.81228082645199995, -0.94330504695600004, 0.67153020783999995, -0.13446586419000001, 0.52456016491599999, -0.99578789329799999, -0.10922561189, 0.44308006468200001, -0.542475557459, 0.89054139110800001, 0.80285491522300001, -0.93882003393299995, -0.94910827801300002, 0.082824945587000001, 0.87829832555700005, -0.23759152462399999, -0.56680120573899995, -0.155766848835, -0.94191842484999999, -0.55661666745399996, -0.124224812699, -0.0083755172362999994, -0.53383109948499996, -0.53826691691799999, -0.56243792532500003, -0.080793068524499995, -0.42043677081899999, -0.95702058946799995, 0.67515595132499995, 0.112908645305, 0.284588725865, -0.62818746821100002, 0.98508682435200001, 0.71989305759099997, -0.75822008038800004, -0.33460962927999999, 0.44296881516699999, 0.42238353939099998, 0.87288117359899997, -0.155786000077, 0.66007138654899999, 0.34061113282799999, -0.39326297813400002, 0.17516121228699999, 0.76495800166399996, 0.69239483685699998, 0.0105676411592, 0.178004515965, -0.93094833969699997, -0.51452005291400005, 0.59480849510900002, -0.17137200139799999, -0.65398519684199996, 0.097597522776300003, 0.40608152413100002, 0.34897166100499999, -0.25059395899699999, -0.122076739911, 0.016852976499999998, 0.55688523000000001, 0.041876835226300001, -0.21348981007199999, -0.020612959075499999, -0.94085007206600002, -0.91302541928699998, 0.40676417720800001, 0.966375434619, 0.18636746075999999, -0.21280062724400001, -0.65930160628900003, 0.0044771168669699999, 0.96415327507699999, 0.54104627966200003, 0.079234896899600005, 0.72057955784100003, -0.53564774387400005, 0.027543326375299999, 0.90493477653700005, 0.15558961560199999, -0.081736536178699998, -0.46144104511700001, 0.095992618932499996, 0.91423256291999999, -0.98858174109899999, 0.56731046523100004, 0.64097182385100004, 0.77235916165200003, 0.48100682366600001, 0.61827980174499997, 0.037356567046000003, 0.122715729557, -0.14781864062399999, -0.88775340495900001, 0.74002031035299998, 0.13999866775299999, -0.60032115964599997, 0.0094409348577299997, -0.030149775544500001, -0.28642007090999999, -0.307844161964, 0.076957591475699999, 0.24697890559499999, 0.22490492956499999, -0.083706399800600004, -0.94405003183199998, -0.54078993744600001, -0.64557748212300003, 0.16892174155699999, 0.72201772170699996, 0.59687788115499996, 0.59419512527100005, 0.63287474112099995, -0.48941191982499999, 0.68348966454799998, 0.34622705087700001, -0.83353172439199996, -0.96661873976900003, -0.97088005015000001, 0.51117355050400004, -0.50088154869299994, -0.78102274541100003, 0.24960416830500001, -0.311154271807, -0.86096924293800003, -0.68074895061200003, 0.054760798095999999, -0.66371010755500004, -0.454171126363, 0.42317985437099997, -0.0905967399087, -0.355996467225, -0.052457971659399999, -0.952730844736, -0.226885790477, -0.158162641582, -0.62392139049700002, -0.78247661510900002, 0.79963700071199995, 0.020231961857400001, -0.58181801489600005, 0.211297280068, 0.63407933675600003, -0.958363782981, -0.96427095834400001, -0.70707651920100001, 0.43767094552399999, -0.67954481474100004, 0.40921125570400002, 0.35635159055400001, 0.089404327157800001, -0.55880050395500003, 0.95118903563599999, 0.59562171541200004, 0.033199033898800002, -0.55360843950700001, 0.29701283619899999, -0.210203980283, 0.151691925576, -0.35750838131000001, 0.26189572254299998]

    # values from Matlab RFFB with various disabled BPMs
    test_subset([],       -28.686464947900227, hcm, bpmresp, disp, rad_over_A)
    test_subset([73],     -24.192671084688385, hcm, bpmresp, disp, rad_over_A)
    test_subset([73, 22], -26.112378103341264, hcm, bpmresp, disp, rad_over_A)
    # increased this by 2 because it's past the 13S BPMs
    test_subset([102],    -31.226833336284535, hcm, bpmresp, disp, rad_over_A)
    
    # run this one again to test inverse matrix cache
    test_subset([],       -28.686464947900227, hcm, bpmresp, disp, rad_over_A)

    # test with EPICS
    test_online(bpmresp, disp, rad_over_A)
    
if __name__ == "__main__":
    run_tests()

# nice tests, now add to IOC
