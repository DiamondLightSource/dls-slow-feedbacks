#!/usr/bin/env dls-python2.6

"""Middlelayer for Python
Second version using RDB and CVS import"""

import sqlite3, csv, numpy, os, Queue
from scipy.io import loadmat
from cothread.catools import *

OPSDATA = "/dls/ops-physics/diamondopsdata"
AOFILE = os.path.join(os.path.dirname(__file__), "ao.csv")
MEMBEROFFILE = os.path.join(os.path.dirname(__file__), "memberof.csv")

# Matrix uses Middlelayer

class Matrix(object):
    "Unpack a Middlelayer Response Matrix"
    def __init__(self, mode, filename):
        fullname = os.path.join(OPSDATA, mode, filename)
        rm = loadmat(fullname)
        mx = []
        familyNames = []
        # this is how Middlelayer does it
        for n in range(rm["Rmat"].shape[1]):
            fam = rm["Rmat"][0,n]
            name = str(fam["Actuator"][0,0]["FamilyName"][0,0][0])
            familyNames.append(name)
            m = numpy.sum(fam["Data"][0,0], 1)
            if fam["UnitsString"][0,0][0] == "(1/MHz)/Amp":
                # chromaticity convert units to (Tune/ddp)/A
                MCF = fam["Monitor"][0,0]["MCF"][0,0][0,0]
                RF = fam["Monitor"][0,0]["Actuator"][0,0]["Data"][0,0][0,0]
                m = m * -MCF * RF
            m.shape = (m.shape[0], 1)
            mx.append(m)
        self.golden = rm["Rmat"][0,0]["Monitor"][0,0]["Data"][0,0]
        mx = numpy.hstack(mx)
        self.mx = mx
        print mx
        self.familyNames = familyNames

class Middlelayer(object):
    "RDB version of Middlelayer Accelerator Object"
    def __init__(self):
        create_ao = "create table ao (family text, status int, readback text, setpoint text, " \
                    "device1 int, device2 int, element int, pos real)"
        insert_ao = "insert into ao (family,status,readback,setpoint,device1,device2,element,pos) values " \
                    "(:family,:status,:readback,:setpoint,:device1,:device2,:element,:pos)"
        create_memberof = "create table memberof (family text, memberof text)"
        insert_memberof = "insert into memberof (family,memberof) values (:family,:memberof)"
        db = sqlite3.connect(":memory:")
        db.text_factory = str
        ins = "insert into ao (family,readback,setpoint,device1,device2,element,pos) values " \
              "(:family,:readback,:setpoint,:device1,:device2,:element,:pos)"
        db.execute(create_ao)
        db.execute(create_memberof)
        for line in csv.DictReader(file(AOFILE)):
            db.execute(insert_ao, line)
        for line in csv.DictReader(file(MEMBEROFFILE)):
            db.execute(insert_memberof, line)
        self.db = db

    def getSetpoint(self, an):
        db = self.db
        db.execute("drop table if exists actuators")
        db.execute("create temporary table actuators (family text, id int)")
        db.executemany("insert into actuators (id, family) values (?, ?)", enumerate(an))
        c = db.cursor()
        c.execute("select setpoint, actuators.id from ao, actuators " \
                  "where ao.family == actuators.family order by actuators.id, element")
        result = c.fetchall()
        return zip(*result)

class Signal(object):
    def __init__(self):
        self.listeners = []
    def fire(self, *args):
        for s in self.listeners:
            s(*args)
    def connect(self, sink):
        self.listeners.append(sink)

class Mux(object):

    def __init__(self, nmax):
        self.Output = Signal()
        self.inputs = [0] * nmax
        self.n = 0
        
    def SetSelector(self, n):
        self.n = n
        self.Output.fire(self.inputs[self.n])
        
    def SetInput(self, n, v):
        self.inputs[n] = v
        self.Output.fire(self.inputs[self.n])

class Correction(object):
    
    RATELIMIT = 1
    
    def __init__(self, mml, filename):
        self.limited = 0
        self.mml = mml
        self.filename = filename
        self.delta = 0
        self.GoalHChanged = Signal()
        self.GoalVChanged = Signal()
        self.LimitedChanged = Signal()
        self.Output = Signal()
        self.tuneh = 0
        self.tunev = 0
        self.goalh = 0
        self.goalv = 0

    def GetLimited(self):
        return self.limited
    def SetLimited(self, limited):
        if self.limited != limited:
            self.limited = limited
            self.LimitedChanged.fire(limited)
    Limited = property(GetLimited, SetLimited)
    
    def GetGoalH(self):
        return self.goalh
    def SetGoalH(self, goal):
        if self.goalh != goal:
            self.goalh = goal
            self.GoalHChanged.fire(goal)
    GoalH = property(GetGoalH, SetGoalH)

    def GetGoalV(self):
        return self.goalv
    def SetGoalV(self, goal):
        if self.goalv != goal:
            self.goalv = goal
            self.GoalVChanged.fire(goal)
    GoalV = property(GetGoalV, SetGoalV)

    def SetTuneH(self, tune):
        self.tuneh = tune

    def SetTuneV(self, tune):
        self.tunev = tune
    
    def SetDelta(self, delta):
        self.delta = delta
        
    def SetMode(self, mode):
        print "setMode", mode
        self.matrix = Matrix(mode, self.filename)
        self.actuators, fam2device = self.mml.getSetpoint(self.matrix.familyNames)
        # invert and expand the per-family response matrix to device size
        self.irm = numpy.linalg.pinv(self.matrix.mx)[fam2device, :]
        self.GoalH = self.matrix.golden[0,0]
        self.GoalV = self.matrix.golden[1,0]

    def StepHUp(self, value):
        self.Step([self.delta, 0])

    def StepHDown(self, value):
        self.Step([-self.delta, 0])

    def StepVUp(self, value):
        self.Step([0, self.delta])

    def StepVDown(self, value):
        self.Step([0, -self.delta])

    def Correct(self, unused):
        delta = [self.goalh - self.tuneh, self.goalv - self.tunev]
        self.Step(delta)

    def Step(self, delta):
        self.x0 = caget(self.actuators)
        dx = numpy.dot(self.irm, delta)
        maxstep = max(abs(dx))
        if maxstep > self.RATELIMIT:
            dx = dx / maxstep * self.RATELIMIT
        self.Limited = max(abs(dx))
        x1 = self.x0 + dx
        self.Output.fire(self.actuators, x1)

# Thursday:  finish this IOC! Nearly done.
