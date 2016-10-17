"""
Test that the element data loaded from mml.sql agrees with what we expect
from aphla.
"""
import pkg_resources
pkg_resources.require('pml')

import numpy
import aphla as ap
import pml
pml.initialise('VMX')
import mml


def test_bpms_loaded():
    ap_bpms = ap.getElements('BPM')
    s = numpy.array([el.sb for el in ap_bpms])
    mml_bpms = mml.ao['bpmx']
    numpy.testing.assert_almost_equal(s, mml_bpms.s, 5)
    mml_bpms = mml.ao['bpmy']
    numpy.testing.assert_almost_equal(s, mml_bpms.s, 5)


def check_pvs_loaded(ap_elements, mml_elements, field):
    sp = numpy.array([el.pv(field=field, handle='setpoint')[0] for el in ap_elements])
    rb = numpy.array([el.pv(field=field, handle='readback')[0] for el in ap_elements])
    numpy.testing.assert_equal(sp, mml_elements.setpoint)
    numpy.testing.assert_equal(rb, mml_elements.readback)


def check_cms_loaded(ap_fam, mml_fam):
    ap_cms = ap.getElements(mml_fam)
    s = numpy.array([el.sb for el in ap_cms])
    mml_cms = mml.ao[ap_fam]
    numpy.testing.assert_almost_equal(s, mml_cms.s, 5)
    check_pvs_loaded(ap_cms, mml_cms, 'b0')
    # Explicitly convert unit to find conversion factor, noting that corrector
    # magnets have a linear conversion.
    ap_hw2phy = numpy.array([cm.convertUnit('b0', 1, None, 'phy') for cm in ap_cms])
    # Compare retrieved and calculated conversion factors.
    numpy.testing.assert_almost_equal(mml_cms.hw2physics, ap_hw2phy)


def test_hcms_loaded():
    check_cms_loaded('hcm', 'HSTR')


def test_vcms_loaded():
    check_cms_loaded('vcm', 'VSTR')
