""" Test that the element data loaded from mml.sql agrees with what we expect
from pytac.
"""
import pkg_resources
pkg_resources.require('pytac')
pkg_resources.require('cothread')

import pytest
import numpy
import mml
import pytac


@pytest.fixture
def lattice():
    return pytac.load_csv.load('DIAD')


def test_bpms_loaded(lattice):
    bpm_s = lattice.get_family_s('BPM')
    mml_bpms = mml.ao['bpmx']
    numpy.testing.assert_almost_equal(bpm_s, mml_bpms.s, 5)
    mml_bpms = mml.ao['bpmy']
    numpy.testing.assert_almost_equal(bpm_s, mml_bpms.s, 5)


def check_pvs_loaded(pytac_elements, mml_elements, field):
    sp = numpy.array([el.get_pv_name(field=field, handle=pytac.SP) for el in pytac_elements])
    rb = numpy.array([el.get_pv_name(field=field, handle=pytac.RB) for el in pytac_elements])
    numpy.testing.assert_equal(sp, mml_elements.setpoint)
    numpy.testing.assert_equal(rb, mml_elements.readback)


@pytest.mark.parametrize('mml_fam,pytac_fam,field',
        (('hcm', 'HSTR', 'b0'), ('vcm', 'VSTR', 'a0'))
)
def test_cms_loaded(lattice, mml_fam, pytac_fam, field):
    pytac_cms = lattice.get_elements(pytac_fam)
    # The entry point of the CMs in pytac is also the entry point
    # of the sext. In MML it is (incorrectly) the exit point of
    # the sext.
    pytac_cm_s_end = [cm.s + cm.length for cm in pytac_cms]
    mml_cms = mml.ao[mml_fam]
    numpy.testing.assert_almost_equal(pytac_cm_s_end, mml_cms.s, 5)
    pytac_cms = lattice.get_elements(pytac_fam)
    check_pvs_loaded(pytac_cms, mml_cms, field)
    # Explicitly convert unit to find conversion factor, noting that corrector
    # magnets have a linear conversion.
    unit_convs = [cm.get_unitconv(field) for cm in pytac_cms]
    pytac_hw2phy = numpy.array([uc.convert(1, pytac.ENG, pytac.PHYS) for uc in unit_convs])
    # Compare retrieved and calculated conversion factors.
    numpy.testing.assert_almost_equal(mml_cms.hw2physics, pytac_hw2phy)
