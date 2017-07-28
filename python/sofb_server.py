import os
import traceback
import mml
from softioc import builder
import cothread
from cothread.catools import caget, ca_nothing
from numpy import *
from scipy.io import loadmat
import sofb

class sofb_server(object):

    def __init__(self, mode):
        self.sofb = sofb.sofb()
        self.power = 0
        self.records()
        self.dataroot = \
            "/dls_sw/work/common/matlab/mml/machine/diamondopsdata"

        mode.add_listener(self.set_datadir)

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
                        self.pv_error.set("OK")
                    else:
                        self.power_pv.set(0)
            except Exception as e:
                self.handle_exception(e)

    def handle_exception(self, exception):
        if isinstance(exception, sofb.CalculationException):
            self.pv_error.set(exception.message)
            self.power_pv.set(0)
            self.calc_error.set(1)
        elif isinstance(exception, ca_nothing):
            self.pv_error.set(e.name)
            self.power_pv.set(0)
            self.calc_error.set(1)
        else:
            self.power_pv.set(0)
            self.calc_error.set(1)
        # Log why we have failed
        traceback.print_exc()

    def single(self, value):
        try:
            self.sofb.correction()
        except Exception as e:
            self.handle_exception(e)

    def records(self):
        builder.SetDeviceName("SR-CS-SOFB-01")

        self.power_pv = builder.mbbOut('ONOFF', ("OFF", 0), ("ON", 1),
                                       initial_value = self.power,
                                       on_update = self.set_power)

        builder.aOut("AFRAC", initial_value = 0.2,
                     DRVH = 1, DRVL = 0, PREC = 4, EGU = "1")

        builder.aOut("MU", 0, initial_value = self.sofb.mu,
            on_update = self.sofb.set_mu, PREC = 3)

        # Corrector magnet ID, in floating point format: cell.position_in_cell
        # This matches the format of SR-DI-EBPM-01:BPMID
        mag_ids = []
        for mag in mml.ao['hcm'].devices:
            if mag[4] == 'S':
                mag_ids.append(int(mag[2:4]) + 0.1*(int(mag[-2:]) - 2))
            elif mag[10:14] == 'SCOR':
                mag_ids.append(int(mag[2:4]) + 0.5 + (2./30)*(int(mag[-2:])))
            else:
                mag_ids.append(int(mag[2:4]) + 0.1*int(mag[-2:]))
        builder.WaveformIn("CMID", initial_value = mag_ids)

        # PVs for demonstrating SVD effect
        svd_length = len(mml.ao['bpmx'].s)
        for plane in ['X', 'Y']:
            sv_pvs = sofb.SingularValuePVs()
            sv_pvs.length = builder.aIn(
                'SVD:%s:LENGTH' % plane, initial_value = svd_length)

            sv_pvs.s = builder.WaveformIn(
                'SVD:%s:S' % plane, initial_value = [0.0]*svd_length)

            sv_pvs.s_inv = builder.WaveformIn(
                'SVD:%s:S_INV' % plane, initial_value = [0.0]*svd_length)

            sv_pvs.s_inv_cut = builder.WaveformIn(
                'SVD:%s:S_INV_CUT' % plane,
                initial_value = [0.0]*svd_length)
            self.sofb.svd[plane] = sv_pvs

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

        self.pv_error = builder.stringIn(
            "EPV", DESC = "PV Error", initial_value = "OK")
