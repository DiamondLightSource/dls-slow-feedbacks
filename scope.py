#!/bin/env python2.4

import sys
sys.path.append("/dls_sw/tools/python2.4/lib/python2.4/site-packages/dls.ca2-2.16-py2.4.egg")
sys.path.append("/dls_sw/tools/python2.4/lib/python2.4/site-packages/dls.thread-1.16-py2.4.egg")

import iqt
from dls.thread import *
from dls.ca2.catools import *
from qt import *

install_threads()

class Scope(QWidget):
    waveform = [0, 1]
    def paintEvent(self, e):
        wave = self.waveform
        hm = min(wave)
        sh = self.height()
        h = self.height() * 1.0 / (max(wave) - hm)
        w = 1.0 * self.width() / len(wave)
        p = QPainter(self)
        p.setPen(QPen(Qt.white))
        p.moveTo(0, 0)
        lineTo = p.lineTo
        drawPoint = p.drawPoint
        for x, y in enumerate(wave):
            y = sh - (y - hm) * h
            # lineTo(int(x * w), y)
            drawPoint(int(x * w), y)
        p.end()

s = Scope()
s.resize(500, 200)
s.setCaption("scope")
s.setPaletteBackgroundColor(Qt.black)
s.show()

def plotme(args):
    if args.status != ECA_NORMAL:
        return
    s.waveform = args.dbr.value
    s.update()

camonitor("SR-CS-PC-01:I_R", plotme)

qApp.setMainWidget(s)
qApp.exec_loop()
