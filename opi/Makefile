all: cors.edl bpms.edl

cors.edl: genedm.py
	./genedm.py

bpms.edl: genedm.py
	./genedm.py

clean:
	rm -f cors.edl bpms.edl *~

.PHONY: clean
