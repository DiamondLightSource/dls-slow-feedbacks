import traceback
import mml
import builder
import iochelper
import cothread
from cothread.catools import caget
from numpy import *
import sofb

class sofb_server(object):
    
    def __init__(self):
        self.sofb = sofb.sofb()
        self.power = 0
        self.records()
        iochelper.on_init.append(self.init)

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
                    self.sofb.correction()
            except:
                traceback.print_exc()

    def single(self, value):
        self.sofb.correction()
                
    def records(self):
        iochelper.SetDevice("SR-CS-SOFB-01")

        builder.mbbOut('ONOFF', ("OFF", 0), ("ON", 1),
                       initial_value = self.power,
                       on_update = self.set_power)
        
        builder.aOut("SVDT", initial_value = self.sofb.threshold,
                     on_update = self.sofb.set_threshold,
                     DRVH = 1, DRVL = 0, PREC = 4, EGU = "Hz")

        builder.aOut("CORRECT", initial_value = 0,
                     on_update = self.single, always_update = True)

        builder.aOut("LIMIT", initial_value = self.sofb.step_limit,
                     DRVH = 1, DRVL = 1e-2,
                     on_update = self.set_limit, PREC = 3)

        
