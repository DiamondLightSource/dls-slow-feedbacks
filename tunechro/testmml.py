#!/usr/bin/env dls-python2.6

from mml2 import *

def fakecaput(xs, ys):
    for (x, y) in zip(xs, ys):
        print "%s %.6f" % (x, y)

class Caget(object):
    def __init__(self):
        self.result = Signal()
    def get(self, xs):
        self.result.fire(caget(xs))
            
g1 = Caget()
g2 = Caget()

mml = Middlelayer()

def show(x):
    print "signal: ", x
    
def testquad():

    c = Correction(mml, "GoldenTuneResp.mat")
    c.GoalHChanged.connect(show)
    c.GoalVChanged.connect(show)
    c.Output.connect(fakecaput)
    c.SetMode("SRI0913")
    c.SetDeltaH(1e-3)
    c.SetDeltaV(1e-3)
    c.requestActuators.connect(g1.get)
    g1.result.connect(c.SetActuators)
    c.Correct(0)

def testsext():

    c = Correction(mml, "GoldenChroResp.mat")
    c.Output.connect(fakecaput)
    c.SetMode("SRI0913")
    c.SetDeltaH(-1)
    c.SetDeltaV(1)
    c.requestActuators.connect(g2.get)
    g2.result.connect(c.SetActuators)
    c.Correct(0)
    
testquad()
testsext()

