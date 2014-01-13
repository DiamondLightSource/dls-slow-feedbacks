#!/dls_sw/work/R3.14.11/support/pythonSoftIoc/pythonIoc
# Slow feedback IOC startup.  Copied from feedback_ioc.py
# for testing tunefb_server.py.

import os, sys
from pkg_resources import require
require('cothread==2.6')
require('scipy==0.8.0b1')
require('iocbuilder==3.23')


if sys.argv[1:]:
    # If running in testing mode log instead of executing caput.  We do this by
    # "monkey patching" catools!
    print "Running in test mode."
    import cothread.catools
    def caput(pvs, values, **kargs):
        print 'caput', pvs, values, kargs
    cothread.catools.caput = caput


from softioc import builder, softioc
from iocbuilder import records

import rffb_server
import tunefb_server

# This import enables caput logging
from softioc import pvlog

# Used externally to select the operating ring mode, used to define appropriate
# feedback parameters internally.
mode = rffb_server.ringmode()

tunefb = tunefb_server.TunefbServer(mode)

# All records created, can now fire up the IOC.
builder.LoadDatabase()
softioc.iocInit()

# Perform post ioc init initialisation for the various components
mode.init()
tunefb.init()

softioc.interactive_ioc(globals())
