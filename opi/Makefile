TOP = ..

all: bpms.edl cors.edl bpms.opi cors.opi runcss.sh

bpms.edl cors.edl: genedm.py
	./genedm.py

bpms.opi cors.opi: bpms.edl cors.edl
	/dls_sw/prod/tools/RHEL6-x86_64/cs-studio/dls-4-5-3/prefix/bin/edm-converter.sh -f bpms.edl cors.edl

clean:
	rm -f bpms.edl cors.edl bpms.opi cors.opi runcss.sh *~

runcss.sh:
	build_run_css -t $(TOP)

.PHONY: clean
