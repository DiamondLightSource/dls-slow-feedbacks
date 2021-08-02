#!/dls_sw/prod/R3.14.12.3/support/pythonSoftIoc/2-6/pythonIoc
# It's important to use pythonIoc for this, otherwise it won't work.

'''
A test database which provides the PVs otherwise provided by the machine,
so that tune feedback can be tested on a different port.
'''

import sys
import random
import time
try:
    import dls_packages
    import cothread
    from softioc import softioc, builder
except ImportError:
    print "You must use the pythonIoc interpreter for this program."
    print "/dls_sw/prod/R3.14.12.3/support/pythonSoftIoc/2-6/pythonIoc"
    sys.exit()


def load_magnet_pvs(txt_file):
    '''
    Load corrector magnet PVs from the specific format
    in the file.
    '''
    mag_pvs = []
    with open(txt_file) as f:
        for line in f:
            mag_pvs.append(line.strip())
    return mag_pvs

# Tune PVs
builder.SetDeviceName('SR23C-DI-TMBF-01')
xtune = builder.aIn('TUNE:TUNE', initial_value=0.204, PREC=4)
builder.SetDeviceName('SR23C-DI-TMBF-02')
ytune = builder.aIn('TUNE:TUNE', initial_value=0.365, PREC=4)
# Beam current PV
builder.SetDeviceName('SR-DI-DCCT-01')
builder.aIn('SIGNAL', initial_value=299.9)

mag_pvs = load_magnet_pvs('../dls_slow_feedbacks/TunePvs.txt')

# Magnet current offset PVs, changed by tune feedback
for mpv in mag_pvs:
    builder.SetDeviceName(mpv)
    builder.aIn('OFFSET1', initial_value=0)

class Server(object):
    '''
    Simple class used to control behaviour of the test PVs.
    '''

    def start(self):
        cothread.Spawn(self.tick)

    def tick(self):
        while True:
            cothread.Sleep(0.5)
            xtune.set(xtune.get() + random.uniform(-0.001, 0.001))
            ytune.set(ytune.get() + random.uniform(-0.001, 0.001))
            # Throw in an occasional spurious tune value
            if random.random() > 0.9:
                old = ytune.get()
                ytune.set(random.uniform(0,10))
                cothread.Sleep(0.5)
                ytune.set(old)



# Start the database
s = Server()
builder.LoadDatabase()
softioc.iocInit()
s.start()
softioc.interactive_ioc(globals())

