all: cors.edl bpms.edl

cors.edl: genedm.py
	./genedm2.py

bpms.edl: genedm.py
	./genedm2.py

clean:
	rm -f cors.edl bpms.edl *~

.PHONY: clean
