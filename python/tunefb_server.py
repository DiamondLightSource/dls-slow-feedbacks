from pkg_resources import require
require('cothread')
require('numpy')
require('scipy')

import os, cothread, scipy, numpy, scipy.io
from cothread.catools import caput, caget
from softioc import builder

class tunefb_server(object):

    def __init__(self, mode):
        self.power = 1

        # Tune data
        self.tune_pvs = [
                'SR21C-DI-TMBF-01:TUNE:TUNE',
                'SR21C-DI-TMBF-02:TUNE:TUNE']
        self.golden_tunes = numpy.array([0.201, 0.371])
        self.max_delta_tunes = numpy.array([0.1, 0.1])
        self.max_tune_variance = numpy.array([0.1, 0.1])
        self.delta_tunes = self.golden_tunes - numpy.array(caget(self.tune_pvs))

        # Current checking values
        self.current_pv = 'SR-DI-DCCT-01:SIGNAL'
        self.min_current = 0.1

        # Injection checking values
        self.injection_pv = 'SR-CS-FILL-01:COUNTDOWN'

        # Load data from files (and on ringmode change)
        self.dataroot = '/home/uxj42447/software/fastfeedback.data'
        self.set_datadir('SRI0913')
        mode.add_listener(self.set_datadir)

        # Initalise EPICS records
        self.records()

    def set_datadir(self, datadir):
        dir = os.path.join(self.dataroot, datadir)

        # Magnet pv names
        raw_pvs = scipy.io.loadmat(os.path.join(dir, 'TunePvs.mat'))
        self.mag_pvs = [
                [pv.encode() for pv in pvs] for pvs in raw_pvs['ans'][0]]

        # Magnet current limits
        self.mag_limits = [[
            numpy.array(caget([pv + 'MIN' for pv in pvs])),
            numpy.array(caget([pv + 'MAX' for pv in pvs]))]
            for pvs in self.mag_pvs]

        # Inverse response matricies
        raw_rms = scipy.io.loadmat(os.path.join(dir, 'GoldenTuneResp.mat'))
        self.irms = []
        for raw_rm in raw_rms['Rmat'][0]:
            self.irms.append((numpy.linalg.pinv(raw_rm[0][0][0])))

    def init(self):
        cothread.Spawn(self.tick)

    def tick(self):
        while True:
            if self.power:
                self.do_correction()
            cothread.Sleep(1.0)

    def check_current(self):
        if caget(self.current_pv) < self.min_current:
            raise Exception('Current to low')

    def is_injection_occuring(self):
        if caget(self.injection_pv) == 0:
            return True
        return False

    def refresh_delta_tunes(self):
        delta_tunes = self.golden_tunes - numpy.array(caget(self.tune_pvs))
        if (abs(delta_tunes - self.delta_tunes) > self.max_delta_tunes).any():
            raise Exception('Tunes are varying to fast')
        self.delta_tunes = delta_tunes
        if (abs(delta_tunes) > self.max_tune_variance).any():
            raise Exception('Tunes outside of permitted range')

    def apply_correction(self, deltas):
        mag_vals = [numpy.array(caget(pvs)) for pvs in self.mag_pvs]
        for i, delta in enumerate(deltas):
            mag_vals[i] += delta
        if numpy.array([
                (x[0] > x[1][1]).any()
                or (x[0] < x[1][0]).any()
                for x in zip(mag_vals, self.mag_limits)]).any():
            raise Exception('Magnet current values exceed tolerances')
        [caput(x[0], x[1]) for x in zip(self.mag_pvs, mag_vals)]

    def do_correction(self):
        try:
            self.check_current()
            if not self.is_injection_occuring():
                self.refresh_delta_tunes()
                deltas = [
                    numpy.dot(irm, self.delta_tunes)
                    for irm in self.irms]
                self.apply_correction(deltas)
        except Exception, e:
            self.set_power(0)
            print 'Error:', e

    def set_power(self, power):
        self.power = power

    def records(self):
        builder.SetDeviceName("SR-CS-TCFB-01")
        self.power_pv = builder.mbbOut('ONOFF', ("OFF", 0), ("ON", 1),
                initial_value = self.power, on_update = self.set_power)
