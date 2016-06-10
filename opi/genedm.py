#!/bin/env dls-python


def header(w, h):
    return """
4 0 1
beginScreenProperties
major 4
minor 0
release 1
x 200
y 200
w %(w)d
h %(h)d
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
""" % locals()


def title(x, y, w, h, value):
    return """
# (Static Text)
object activeXTextClass
beginObjectProperties
major 4
minor 1
release 0
x %(x)d
y %(y)d
w %(w)d
h %(h)d
font "arial-medium-r-18.0"
fontAlign "center"
fgColor index 14
bgColor index 73
value {
  "%(value)s"
}
endObjectProperties
""" % locals()


def label(x, y, w, h, value, color=8, border_width=0):
    text = """
# (Static Text)
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
fgColor index 14
bgColor index %(color)d
value {
          "%(value)s"
          }
"""
    if border_width:
        text = text + "border\n"
        text = text + "lineWidth %(border_width)d\n"
    text = text + "endObjectProperties\n"
    return text % locals()


def rectangle(x, y, w, h, pv=None, color=83, alarm=False, vis_pv=None):
    text = """
# (Rectangle)
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
fillColor index %(color)d
"""
    if alarm:
        text = text + "fillAlarm\n"
    text = text + "lineWidth 0\n"
    if pv:
        text = text + "alarmPv %(pv)s\n"
    if vis_pv:
        text = text + "visPv %(vis_pv)s\n"
        text = text + "visMin \"0\"\n"
        text = text + "visMax \"1\"\n"
    text = text + "endObjectProperties\n"
    return text % locals()


def related(x, y, w, h, deviceh, devicev, display='enable.edl'):
    return """# (Related Display)
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
  0 "%(display)s"
}
symbols {
  0 "deviceh=%(deviceh)s,devicev=%(devicev)s"
}
endObjectProperties
""" % locals()


class Layout(object):

    """Create EDM GUIs consiting of a 2D grid with lables."""

    PADDING = 4
    TITLE_HEIGHT = 40

    def __init__(self, title, x_names, y_names, region, region_func):
        """
        Setup a grid of EDM widgets.
            x_names     -- Array of strings for use as X lables
            y_names     -- Array of strings for use as Y lables
            region      -- Tuple of ints specifying the dimensions of
                           the region in which each element is shown
            region_func -- Callback function that draws in the region
        """
        self.title = title
        self.x_names = x_names
        self.y_names = y_names
        self.region = region
        self.region_func = region_func
        self.nodes = []
        self._make_lables()
        self._make_regions()
        self._make_title()

    def produce(self):
        """Produce the string data representing the EDM GUI."""
        out = []
        out.append(header(*self._calculate_boundaries()))
        for node in self.nodes:
            out.append(node)
        return ''.join(out)

    def _make_lables(self):
        width = self.region[0]
        height = self.region[1]
        x0 = 2 * self.PADDING + width
        y0 = 2 * self.PADDING + self.TITLE_HEIGHT
        for i, x_name in enumerate(self.x_names):
            x = x0 + i * (width + self.PADDING)
            y = y0
            self.nodes.append(label(x, y, width, height, x_name))
        x0 = self.PADDING
        y0 = 3 * self.PADDING + height + self.TITLE_HEIGHT
        for i, y_name in enumerate(self.y_names):
            x = x0
            y = y0 + i * (height + self.PADDING)
            self.nodes.append(label(x, y, width, height, y_name))

    def _make_regions(self):
        width = self.region[0]
        height = self.region[1]
        x0 = 2 * self.PADDING + width
        y0 = 3 * self.PADDING + height + self.TITLE_HEIGHT
        for i, __ in enumerate(self.x_names):
            for j, __ in enumerate(self.y_names):
                x = x0 + i*(self.PADDING + width)
                y = y0 + j*(self.PADDING + height)
                self.nodes.append(self.region_func(i, j, x, y))

    def _make_title(self):
        (w, __) = self._calculate_boundaries()
        self.nodes.append(title(self.PADDING, self.PADDING,
            w - 2*self.PADDING, self.TITLE_HEIGHT, self.title))

    def _calculate_boundaries(self):
        width = (self.PADDING +
                (len(self.x_names) + 1) * (self.PADDING + self.region[0]))
        height = (2 * self.PADDING + self.TITLE_HEIGHT +
                (len(self.y_names) + 1) * (self.PADDING + self.region[1]))
        return (width, height)


CORRECTOR_REGION = [20, 24]
RATES = ['SLOW', 'FAST']
def corrector_func(i, j, x, y):
    quart_region = [CORRECTOR_REGION[0]/2, CORRECTOR_REGION[1]/2]
    devs = ["SR%02dA-PC-%sSTR-%02d" % (i+1, 'HV'[p], j-1) for p in [0, 1]]
    if j in [0, 1]:  ## Skip cells without mini beta correctors
        if i not in [8, 12]:
            return ""
        devs = ["SR%02dS-PC-%sSTR-%02d" % (i+1, 'HV'[p], j+1) for p in [0, 1]]
    pvs = [d + ':%s:DISABLED' % r for r in RATES for d in devs]
    return (
        rectangle(x, y, *quart_region, color=19) +
        rectangle(x, y, *quart_region, color=15, vis_pv=pvs[0]) +
        rectangle(x + quart_region[0], y, *quart_region, color=19) +
        rectangle(x + quart_region[0], y, *quart_region, color=15,
            vis_pv=pvs[1]) +
        rectangle(x, y + quart_region[1], *quart_region, color=19) +
        rectangle(x, y + quart_region[1], *quart_region, color=15,
            vis_pv=pvs[2]) +
        rectangle(x + quart_region[0], y + quart_region[1], *quart_region,
            color=19) +
        rectangle(x + quart_region[0], y + quart_region[1], *quart_region,
            color=15, vis_pv=pvs[3]) +
        related(x, y, *(CORRECTOR_REGION + devs), display='cor_enable.edl'))

corrector_definition = {
        'title': "SOFB and FOFB Corrector Enable",
        'x_names': ['%02d' % x for x in range(1, 25)],
        'y_names': ['S1', 'S2'] + ['%02d' % x for x in range(1, 8)],
        'region': CORRECTOR_REGION,
        'region_func': corrector_func,
        }


BPM_REGION = [20, 25]
BPM_HEADER = 5
def bpm_func(i, j, x, y):
    quart_region = [BPM_REGION[0]/2, (BPM_REGION[1] - BPM_HEADER) / 2]
    bpm_dev = "SR%02dC-DI-EBPM-%02d:CF:ENABLED_S" % (i+1, j-1)
    devs = ["SR%02dC-PC-%sBPM-%02d" % (i+1, 'HV'[p], j-1) for p in [0, 1]]
    if j in [0, 1]:  ## Skip cells without mini beta correctors
        if i not in [8, 12]:
            return ""
        devs = ["SR%02dS-PC-%sBPM-%02d" % (i+1, 'HV'[p], j+1) for p in [0, 1]]
        bpm_dev = "SR%02dC-DI-EBPM-%02d:CF:ENABLED_S" % (i+1, j+1)
    if j in [9] and i not in [1]:  # Add 8th BPM to cell 2 only
        return ""
    pvs = [d + ':%s:DISABLED' % r for r in RATES for d in devs]
    return (
        rectangle(x, y, BPM_REGION[0], BPM_HEADER, color=15, alarm=True,
            pv=bpm_dev) +
        rectangle(x, y+BPM_HEADER, *quart_region, color=19) +
        rectangle(x, y+BPM_HEADER, *quart_region, color=15, vis_pv=pvs[0]) +
        rectangle(x+quart_region[0], y+BPM_HEADER, *quart_region, color=19) +
        rectangle(x+quart_region[0], y+BPM_HEADER, *quart_region, color=15,
            vis_pv=pvs[1]) +
        rectangle(x, y+BPM_HEADER+quart_region[1], *quart_region, color=19) +
        rectangle(x, y+BPM_HEADER+quart_region[1], *quart_region, color=15,
            vis_pv=pvs[2]) +
        rectangle(x+quart_region[0], y+BPM_HEADER+quart_region[1],
            *quart_region, color=19) +
        rectangle(x+quart_region[0], y+BPM_HEADER+quart_region[1],
            *quart_region, color=15, vis_pv=pvs[3]) +
        related(x, y, *(CORRECTOR_REGION + devs), display='cor_enable.edl'))

bpm_definition = {
        'title': "SOFB and FOFB BPM Mask",
        'x_names': ['%02d' % x for x in range(1, 25)],
        'y_names': ['S1', 'S2'] + ['%02d' % x for x in range(1, 9)],
        'region': BPM_REGION,
        'region_func': bpm_func,
        }


def corrector_key():
    x = 558
    y = 6
    h = 18
    w = 20
    return (
        label(x,   y,   w, h, 'SH', color=3, border_width=1) +
        label(x+w, y,   w, h, 'SV', color=3, border_width=1) +
        label(x,   y+h, w, h, 'FH', color=3, border_width=1) +
        label(x+w, y+h, w, h, 'FV', color=3, border_width=1)
    )


def corrector_info():
    text = 'RF feedback always uses all correctors'
    return label(360, 82, 240, 16, text, color=3)


def bpm_key():
if __name__ == '__main__':
    layout = Layout(**corrector_definition)
    with open('cors.edl', 'w') as f:
        f.write(layout.produce() + corrector_key() + corrector_info())
    layout = Layout(**bpm_definition)
    with open('bpms.edl', 'w') as f:
        f.write(layout.produce())

