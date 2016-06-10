#!/bin/env python

"generate corrector enable screen"

exit_ = """
# (Exit Button)
object activeExitButtonClass
beginObjectProperties
major 4
minor 1
release 0
x %(x)d
y %(y)d
w %(w)d
h %(h)d
fgColor index 46
bgColor index 3
topShadowColor index 0
botShadowColor index 14
label "EXIT"
font "helvetica-medium-r-12.0"
3d
endObjectProperties
"""

related = """# (Related Display)
object relatedDisplayClass
beginObjectProperties
major 4
minor 2
release 0
x %(x)d
y %(y)d
w %(w)d
h %(h)d
fgColor index 14
bgColor index 0
topShadowColor index 0
botShadowColor index 14
font "arial-medium-r-18.0"
invisible
numPvs 4
numDsps 1
displayFileName {
  0 "enable.edl"
}
symbols {
  0 "deviceh=%(deviceh)s,devicev=%(devicev)s"
}
endObjectProperties
"""

title = """# (Static Text)
object activeXTextClass
beginObjectProperties
major 4
minor 1
release 0
x 8
y 8
w 592
h 40
font "arial-medium-r-18.0"
fontAlign "center"
fgColor index 14
bgColor index 73
value {
  "$(mode_string) Feedback Corrector Enable"
}
endObjectProperties
"""

text = """# (Static Text)
object activeXTextClass
beginObjectProperties
major 4
minor 1
release 0
x %(x)d
y %(y)d
w %(w)d
h %(h)d
font "helvetica-medium-r-12.0"
fontAlign "center"
fgColor index 1
bgColor index 8
value {
  "%(value)s"
}
endObjectProperties
"""

header = """4 0 1
beginScreenProperties
major 4
minor 0
release 1
x 200
y 200
w %(xm)d
h %(ym)d
font "arial-medium-r-18.0"
ctlFont "arial-medium-r-18.0"
btnFont "arial-medium-r-18.0"
fgColor index 14
bgColor index 3
textColor index 14
ctlFgColor1 index 14
ctlFgColor2 index 0
ctlBgColor1 index 0
ctlBgColor2 index 14
topShadowColor index 0
botShadowColor index 14
endScreenProperties
"""

rectangle = """# (Rectangle)
object activeRectangleClass
beginObjectProperties
major 4
minor 0
release 0
x %(x)d
y %(y)d
w %(w)d
h %(h)d
lineColor index 14
fill
fillColor index 83
lineWidth 0
alarmPv "%(pv)s"
endObjectProperties
"""

redrectangle = """# (Rectangle)
object activeRectangleClass
beginObjectProperties
major 4
minor 0
release 0
x %(x)d
y %(y)d
w %(w)d
h %(h)d
lineColor index 14
fill
fillColor index 21
lineWidth 0
endObjectProperties
"""

size = 16
delta = 8
w = size
h = size

CELLS = 24
MAGS = 7

tsize = (size + delta) * 2

xm = (CELLS + 1) * (size + delta) + delta
ym = (MAGS + 3) * (size + delta) + delta + tsize + (24 + delta)

print header % locals()

for cell in range(CELLS):
    x = (cell + 1) * (size + delta) + delta
    y = delta + tsize
    value = "%02d" % (cell + 1)
    print text % locals()

for i in range(-2, MAGS):
    x = delta
    y = (i + 3) * (size + delta) + delta + tsize
    value = "%02d" % (i + 1)
    if i <  0:
        value = "S%d" % (i + 3)
    print text % locals()

for cell in range(CELLS):
    for i in range(MAGS):
        deviceh = "SR%02dA-PC-HSTR-%02d" % (cell + 1, i + 1)
        devicev = "SR%02dA-PC-VSTR-%02d" % (cell + 1, i + 1)
        x = (cell + 1) * (size + delta) + delta
        y = (i + 3) * (size + delta) + delta + tsize

        w = size / 2
        pv = "%s:$(mode):DISABLED" % deviceh
        print rectangle % locals()

        x = x + w
        pv = "%s:$(mode):DISABLED" % devicev
        print rectangle % locals()

        # this is fairly stupid
        x = x - w
        w = size
        print related % locals()

for mbcell in [9, 13]:
    for i in range(2):
        deviceh = "SR%02dS-PC-HSTR-%02d" % (mbcell, i + 1)
        devicev = "SR%02dS-PC-VSTR-%02d" % (mbcell, i + 1)
        x = mbcell * (size + delta) + delta
        y = (i + 1) * (size + delta) + delta + tsize
        pv = "%s:$(mode):DISABLED" % deviceh
        w = size / 2
        print rectangle % locals()
        x = x + w
        pv = "%s:$(mode):DISABLED" % devicev
        print rectangle % locals()

        x = x - w
        w = size
        print related % locals()

print title
print exit_ % {"x": xm - 48 - delta, "y": ym - 24 - delta, "w": 48, "h": 24}
