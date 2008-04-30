all: install

install:
	./magnets.py > magnets.db

clean:
	-rm *.pyc *~ magnets.db

