families = {}

class struct(object):
    def __init__(self, name, *args, **kw):
        self.name = name
        self.L = 0
        for (k, v) in kw.items():
            setattr(self, k, v)
        families[name] = self

class marker(struct): pass
class bpm(struct): pass
class drift(struct): pass
class quadrupole(struct): pass
class sextupole(struct): pass
class bending(struct): pass

