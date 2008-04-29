#!/dls_sw/prod/R3.14.8.2/support/pyIoc/1-2/bin/linux-x86/softIoc -s
dbLoadDatabase("magnets.db")
iocInit()
epicsEnvSet("PYTHONPATH", ".")
Python("import magnets")
