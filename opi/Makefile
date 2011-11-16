all: cors.edl

cors.edl: genedm.py
	./genedm.py > $@

clean:
	rm -f cors.edl *~

.PHONY: clean
