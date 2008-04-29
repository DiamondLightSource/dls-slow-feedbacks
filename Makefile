all: install

install:
	./makedb.py > magnets.db

clean:
	-rm *.pyc *~ magnets.db

