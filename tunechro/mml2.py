#!/usr/bin/env dls-python2.6

"""Middlelayer for Python
Second version using RDB and CVS import"""

import sqlite3, csv, numpy, os, Queue
from pkg_resources import require
require("scipy==0.8.0b1")
require("cothread==2.8")
from scipy.io import loadmat
from cothread.catools import *

OPSDATA = "/dls/ops-physics/diamondopsdata"

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
        for line in csv.DictReader(file("ao.csv")):
            db.execute(insert_ao, line)
        for line in csv.DictReader(file("memberof.csv")):
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

class Correction(object):
    
    RATELIMIT = 0.01 * 1e9
    
    def __init__(self, mml, filename):
        self.mml = mml
        self.filename = filename
        self.deltah = 0
        self.deltav = 0
        self.requestActuators = Signal()
        self.GoalHChanged = Signal()
        self.GoalVChanged = Signal()
        self.Output = Signal()
        self.tuneh = 0
        self.tunev = 0
        self.goalh = 0
        self.goalv = 0

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
        print "SetTuneH", tune
        self.tuneh = tune
        self.Update()

    def SetTuneV(self, tune):
        self.tunev = tune
    
    def SetDeltaH(self, delta):
        self.deltah = delta
        
    def SetDeltaV(self, delta):
        self.deltav = delta
    
    def SetMode(self, mode):
        print "setMode", mode
        self.matrix = Matrix(mode, self.filename)
        self.actuators, fam2device = self.mml.getSetpoint(self.matrix.familyNames)
        # invert and expand the per-family response matrix to device size
        self.irm = numpy.linalg.pinv(self.matrix.mx)[fam2device, :]
        self.GoalH = self.matrix.golden[0,0]
        self.GoalV = self.matrix.golden[1,0]

    def SetActuators(self, value):
        self.x0 = value

    def Update(self):
        self.x0 = caget(self.actuators)
        dx = numpy.dot(self.irm,
                       [self.goalh - self.tuneh,
                        self.goalv - self.tunev])
        maxstep = max(abs(dx))
        if maxstep > self.RATELIMIT:
            dx = dx / maxstep * self.RATELIMIT
        x1 = self.x0 + dx
        self.Output.fire(self.actuators, x1)
    
    def Correct(self, dummy):
        # self.requestActuators.fire(self.actuators)
        self.x0 = caget(self.actuators)
        dx = numpy.dot(self.irm, [self.deltah, self.deltav])
        maxstep = max(abs(dx))
        if maxstep > self.RATELIMIT:
            dx = dx / maxstep * self.RATELIMIT
        x1 = self.x0 + dx
        self.Output.fire(self.actuators, x1)

# 1) feedback option for the tune, wait on chromaticity
# Golden Tunes?

"""
ao.TUNE.Monitor.Golden = [.205; .36];
if strcmpi(srmode,'SRI13')
ao.TUNE.Monitor.Golden = [.230; .180];
elseif strcmpi(srmode,'SRI0913')
ao.TUNE.Monitor.Golden = [.201; .371];
%     ao.TUNE.Monitor.Golden = [.22; .36];
elseif strcmpi(srmode,'SRI09')
ao.TUNE.Monitor.Golden = [.230; .180];
elseif strcmpi(srmode,'SR3ps')
ao.TUNE.Monitor.Golden = [.150; .397];
elseif strcmpi(srmode,'SR1ps')
ao.TUNE.Monitor.Golden = [.150; .397];
elseif strcmpi(srmode,'SRm1ps')
ao.TUNE.Monitor.Golden = [.150; .397];
elseif strcmp(srmode, 'SRzd')
ao.TUNE.Monitor.Golden = [0.28; 0.222];
elseif strcmpi(srmode,'SRLE3ps')
ao.TUNE.Monitor.Golden = [0.3894; 0.2835];
elseif strcmpi(srmode,'SRLEm3ps')
ao.TUNE.Monitor.Golden = [0.3894; 0.2847];
elseif strcmpi(srmode,'SRLETHz')
ao.TUNE.Monitor.Golden = [0.3892; 0.2847];
end
"""

# Wednesday: finish this IOC, First Direct apply for ISA
# Thursday:  finish this IOC! Nearly done.

# mml = Middlelayer()

# signal and slots for Python
