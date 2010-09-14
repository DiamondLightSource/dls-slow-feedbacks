import os
import traceback
import mml
import builder
import iochelper
import cothread
from cothread.catools import caget
from numpy import *
from scipy.io import loadmat
import sofb

class sofb_server(object):
    
    def __init__(self):
        self.sofb = sofb.sofb()
        self.power = 0
        self.records()
        self.dataroot = "/home/diamond/common/matlab/middlelayer/2-0/machine/diamondopsdata"
        iochelper.on_init.append(self.init)

    def set_datadir(self, datadir):
        self.sofb.cache.clear()
        path = os.path.join(self.dataroot, datadir)
        try:
            bpmresp = loadmat(os.path.join(path, "GoldenBPMResp"))
            assert(bpmresp["Rmat"][0,0]["Units"] == "Hardware")
            self.sofb.rmx = bpmresp["Rmat"][0,0]["Data"]
            self.sofb.rmy = bpmresp["Rmat"][1,1]["Data"]
            print "SOFB loaded matrix %s" % datadir
            self.matrix_error.set(0)
        except:
            traceback.print_exc()
            self.sofb.rmx = None
            self.sofb.rmy = None
            self.matrix_error.set(1)

    def set_power(self, power):
        self.power = power

    def set_limit(self, limit):
        self.sofb.step_limit = limit

    def init(self):
        cothread.Spawn(self.tick)

    def tick(self):
        while True:
            cothread.Sleep(1.0)
            try:
                if self.power:
                    # no loop below 2mA
                    current = caget("SR-DI-DCCT-01:SIGNAL")
                    if current > 2:
                        self.sofb.correction()
                        self.calc_error.set(0)
                    else:
                        self.power_pv.set(0)
            except:
                traceback.print_exc()
                self.power_pv.set(0)
                self.calc_error.set(1)

    def single(self, value):
        self.sofb.correction()
                
    def records(self):
        iochelper.SetDevice("SR-CS-SOFB-01")

        self.power_pv = builder.mbbOut('ONOFF', ("OFF", 0), ("ON", 1),
                                       initial_value = self.power,
                                       on_update = self.set_power)
        
        builder.aOut("SVDT", initial_value = self.sofb.threshold,
                     on_update = self.sofb.set_threshold,
                     DRVH = 1, DRVL = 0, PREC = 4, EGU = "Hz")

        builder.aOut("CORRECT", initial_value = 0,
                     on_update = self.single, always_update = True)

        builder.aOut("LIMIT", initial_value = self.sofb.step_limit,
                     DRVH = 0.5, DRVL = 1e-3,
                     on_update = self.set_limit, PREC = 3)

        self.matrix_error = builder.boolIn(
            "EMATRIX", DESC = "Matrix Error",
            initial_value = 1, ZNAM = "OK",
            ONAM = "SOFB MATRIX")
        
        self.calc_error = builder.boolIn(
            "ECALC", DESC = "Calculation Error",
            initial_value = 0, ZNAM = "OK",
            ONAM = "SOFB CALC")


        
