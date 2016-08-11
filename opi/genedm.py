#!/bin/env dls-python


def header(w, h):
    """Generate text that must appear at the start of an EDM file"""
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
    """Generate text representing an EDM diagnostics title bar"""
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
    """Generate text representing a simple EDM bordered labl"""
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
    """Generate text representing an EDM rectangle"""
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
    """Generate text representing an EDM related display widget"""
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
        """Add the labels along the top and down the left of the GUI"""
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
        """Use the user provided callback to generate table cells"""
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
        """Insert a title widget at the top of the GUI"""
        (w, __) = self._calculate_boundaries()
        self.nodes.append(title(self.PADDING, self.PADDING,
            w - 2*self.PADDING, self.TITLE_HEIGHT, self.title))

    def _calculate_boundaries(self):
        """Determine size of the GUI based on number of rows and columns"""
        width = (self.PADDING +
                (len(self.x_names) + 1) * (self.PADDING + self.region[0]))
        height = (2 * self.PADDING + self.TITLE_HEIGHT +
                (len(self.y_names) + 1) * (self.PADDING + self.region[1]))
        return (width, height)


def generate_quad(x, y, region, pvs, devs):
    """Generate four rectangles that can be toggeled depending on PVs"""
    quart_region = [region[0]/2, region[1]/2]
    return (
        rectangle(x, y, *quart_region, color=19) +
        rectangle(x, y, *quart_region, color=15, vis_pv=pvs[0]) +
        rectangle(x+quart_region[0], y, *quart_region, color=19) +
        rectangle(x+quart_region[0], y, *quart_region, color=15,
            vis_pv=pvs[1]) +
        rectangle(x, y+quart_region[1], *quart_region, color=19) +
        rectangle(x, y+quart_region[1], *quart_region, color=15,
            vis_pv=pvs[2]) +
        rectangle(x+quart_region[0], y+quart_region[1],
            *quart_region, color=19) +
        rectangle(x+quart_region[0], y+quart_region[1],
            *quart_region, color=15, vis_pv=pvs[3]) +
        related(x, y, *(region + devs), display='enable.edl'))


def corrector_key():
    """Generate text representing the corrector magnet key"""
    x = 558
    y = 6
    h = 17
    w = 20
    return (
        label(x,   y,   w+1, h+1, 'SH', color=3, border_width=1) +
        label(x+w, y,   w,   h+1, 'SV', color=3, border_width=1) +
        label(x,   y+h, w+1, h,   'FH', color=3, border_width=1) +
        label(x+w, y+h, w,   h,   'FV', color=3, border_width=1))


def corrector_info():
    """Add label giving info about the corrector GUI"""
    text = 'RF feedback always uses all correctors'
    return label(360, 82, 240, 16, text, color=3)


def corrector_dyanmics():
    """Add warning about using slow correctors with FOFB"""
    return (
            label(44, 283, 8,  14, '', color=6) +
            label(73, 283, 100, 14, 'Do not use', color=6))


def bpm_key():
    """Generate text representing the bpm key"""
    x = 558
    y = 78
    h = 17
    w = 20
    return (
        label(x,   y,     w*2, h+1, 'master', color=3, border_width=1) +
        label(x,   y+h,   w+1, h+1, 'SH', color=3, border_width=1) +
        label(x+w, y+h,   w,   h+1, 'SV', color=3, border_width=1) +
        label(x,   y+2*h, w+1, h, 'FH', color=3, border_width=1) +
        label(x+w, y+2*h, w,   h, 'FV', color=3, border_width=1))


def bpm_info():
    """Add label giving info about the BPM GUI"""
    # Use spaces as a crude padding due to centered text on widget
    text = 'All globally enabled BPMs\nare used by RF feedback  '
    return label(354, 80, 164, 32, text, color=3)


CORRECTOR_REGION = [20, 24]
RATES = ['SLOW', 'FAST']
def corrector_func(i, j, x, y):
    """Callback function to generate cells on the corrector GUI"""
    quart_region = [CORRECTOR_REGION[0]/2, CORRECTOR_REGION[1]/2]
    if j < 7:  ## Align numbered rows with labels
        devs = ["SR%02dA-PC-%sSTR-%02d" % (i+1, 'HV'[p], j-1) for p in [0, 1]]
    else:
        devs = ["SR%02dA-PC-%sSTR-%02d" % (i+1, 'HV'[p], j-3) for p in [0, 1]]
    if j in [0, 1]:
        if i not in [8, 12]:  ## Skip cells without mini beta correctors
            return ""
        devs = ["SR%02dS-PC-%sSTR-%02d" % (i+1, 'HV'[p], j+1) for p in [0, 1]]
    if j in [7, 8, 11, 12] and i not in [1]:  # Skip non DDBA correctors
        return ""
    if i in [1] and j in [3, 4, 9]:  # Skip correctors not in DDBA cell
        return ""
    if i in [1] and j in [7, 8]:
        devs = ["SR%02dA-PC-%sSCOR-%02d" % (i+1, 'HV'[p], j-6) for p in [0, 1]]
    if j in [12]:
        devs = ["SR%02dA-PC-%sSTR-%02d" % (i+1, 'HV'[p], j-2) for p in [0, 1]]
    pvs = [d + ':%s:DISABLED' % r for r in RATES for d in devs]
    return generate_quad(x, y, CORRECTOR_REGION, pvs, devs)

corrector_definition = {
        'title': "SOFB and FOFB Corrector Enable",
        'x_names': ['%02d' % x for x in range(1, 25)],
        'y_names': ['S1', 'S2', '01', '02', '03', '04', '05',
            'C1', 'C2', '06', '07', '08', '10'],
        'region': CORRECTOR_REGION,
        'region_func': corrector_func,
        }


BPM_REGION = [20, 25]
BPM_HEADER = 5
def bpm_func(i, j, x, y):
    """Callback function to generate cells on the BPM GUI"""
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
        generate_quad(x, y+BPM_HEADER,
            [BPM_REGION[0], BPM_REGION[1] - BPM_HEADER], pvs, devs))

bpm_definition = {
        'title': "SOFB and FOFB BPM Mask",
        'x_names': ['%02d' % x for x in range(1, 25)],
        'y_names': ['S1', 'S2'] + ['%02d' % x for x in range(1, 9)],
        'region': BPM_REGION,
        'region_func': bpm_func,
        }


if __name__ == '__main__':
    # instantiate layout objects, add extra labels, and write to file
    layout = Layout(**corrector_definition)
    with open('cors.edl', 'w') as f:
        f.write(layout.produce() + corrector_key() +
                corrector_info() + corrector_dyanmics())
    layout = Layout(**bpm_definition)
    with open('bpms.edl', 'w') as f:
        f.write(layout.produce() + bpm_key() + bpm_info())

