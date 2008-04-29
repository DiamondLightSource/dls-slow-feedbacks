#!/bin/env python2.4

from ctypes import *

libdbIoc = CDLL("/dls_sw/epics/R3.14.8.2/base/lib/linux-x86/libdbIoc.so")

# ca monitors
libca = CDLL("/dls_sw/epics/R3.14.8.2/base/lib/linux-x86/libca.so")
libca.ca_name.restype = c_char_p
libca.ca_message.restype = c_char_p

# only for DOUBLE
class event_handler_args(Structure):
    _fields_ = (("usr",    c_int),
                ("chid",   c_int),
                ("type",   c_int),
                ("count",  c_int),
                ("dbr",    POINTER(c_double)),
                ("status", c_int))

event_handler = CFUNCTYPE(None, event_handler_args)

ECA_NORMAL = 1
DBR_DOUBLE = 6

(DBE_VALUE,
 DBE_LOG,
 DBE_ALARM) = (1, 2, 4)

(DBF_STRING,
 DBF_CHAR,
 DBF_UCHAR,
 DBF_SHORT,
 DBF_USHORT,
 DBF_LONG,
 DBF_ULONG,
 DBF_FLOAT,
 DBF_DOUBLE) = range(9)

class dbAddr(Structure):
    _fields_ = (("precord", c_void_p),
                ("pfield", c_void_p),
                ("pfldDes", c_void_p),
                ("asPvt", c_void_p),
                ("no_elements", c_long),
                ("field_type", c_short),
                ("field_size", c_short),
                ("special", c_short),
                ("dbr_field_type", c_short))

libdbIoc.dbGetField.argtypes = (c_void_p, c_short, c_int,
                                c_void_p, c_void_p, c_void_p)

libdbIoc.dbPutField.argtypes = (c_void_p, c_short, c_int, c_int)

fs = ["dbPutField",
      "dbGetField",
      "dbNameToAddr"]

for f in fs:
    globals()[f] = getattr(libdbIoc, f)

__all__ = fs + ["dbAddr", "ECA_NORMAL", "libca",
                "DBR_DOUBLE", "DBE_VALUE", "event_handler"]

@event_handler
def test_callback(args):
    print "hello", args.dbr[0]

def test():
    import time
    chid = c_void_p()
    evid = c_void_p()
    assert(libca.ca_context_create(1) == ECA_NORMAL)
    # attach thread to context
    libca.ca_attach_context(libca.ca_current_context())
    # no connection callback -> this is a local record
    assert(libca.ca_create_channel("SR21C-DI-EBPM-01:SA:X", 0, 0, 0, byref(chid)) == ECA_NORMAL)
    # want this for event-driven processing
    assert(libca.ca_create_subscription(DBR_DOUBLE, 0, chid, DBE_VALUE, test_callback, 0, byref(evid)) == ECA_NORMAL)
    time.sleep(5)
    
if __name__ == "__main__":
    test()
    
