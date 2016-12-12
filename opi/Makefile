TOP = ..

all: cors.edl bpms.edl runcss.sh

bpms.edl cors.edl: genedm.py
	./genedm.py

clean:
	rm -f cors.edl bpms.edl *~

runcss.sh:
	build_run_css -t $(TOP)

.PHONY: clean
