# Licensed under a 3-clause BSD style license - see LICENSE.rst
from __future__ import absolute_import, division, print_function, unicode_literals
import numpy as np
from numpy.testing import assert_allclose
from numpy.testing import assert_equal
from astropy.tests.helper import assert_quantity_allclose
from astropy.table import Table
import astropy.units as u
from astropy.wcs import WCS
from astropy.units import Quantity
from astropy.coordinates import Angle, SkyCoord
from astropy.modeling.models import Gaussian1D
from ...utils.testing import requires_dependency, requires_data
from ...datasets import gammapy_extra
from ...background import GaussianBand2D, CubeBackgroundModel, EnergyOffsetBackgroundModel
from ...utils.energy import EnergyBounds
from ...data import ObservationTable
from ...data import DataStore, EventList
from ...region import SkyCircleRegion
from ...background.models import _compute_pie_fraction, _select_events_outside_pie
from ...image import make_empty_image
from ...image import coordinates, bin_events_in_image, make_empty_image


@requires_dependency('scipy')
class TestGaussianBand2D:
    def setup(self):
        table = Table()
        table['x'] = [-30, -10, 10, 20]
        table['amplitude'] = [0, 1, 10, 0]
        table['mean'] = [-1, 0, 1, 0]
        table['stddev'] = [0.4, 0.5, 0.3, 1.0]
        self.table = table
        self.model = GaussianBand2D(table)

    def test_evaluate(self):
        x = np.linspace(-100, 20, 5)
        y = np.linspace(-2, 2, 7)
        x, y = np.meshgrid(x, y)
        image = self.model.evaluate(x, y)
        assert_allclose(image.sum(), 1.223962643740966)

    def test_parvals(self):
        par = self.model.parvals(-30)
        assert_allclose(par['amplitude'], 0)
        assert_allclose(par['mean'], -1)
        assert_allclose(par['stddev'], 0.4)

    def test_y_model(self):
        model = self.model.y_model(-30)
        assert isinstance(model, Gaussian1D)
        assert_allclose(model.parameters, [0, -1, 0.4])


@requires_data('gammapy-extra')
class TestCubeBackgroundModel:
    def test_read(self):

        # test shape and scheme of cubes when reading a file
        filename = gammapy_extra.filename('test_datasets/background/bg_cube_model_test2.fits.gz')
        bg_cube_model = CubeBackgroundModel.read(filename, format='table')
        cubes = [bg_cube_model.counts_cube,
                 bg_cube_model.livetime_cube,
                 bg_cube_model.background_cube]
        schemes = ['bg_counts_cube', 'bg_livetime_cube', 'bg_cube']
        for cube, scheme in zip(cubes, schemes):
            assert len(cube.data.shape) == 3
            assert cube.data.shape == (len(cube.energy_edges) - 1,
                                       len(cube.coordy_edges) - 1,
                                       len(cube.coordx_edges) - 1)
            assert cube.scheme == scheme

    def test_write(self, tmpdir):

        filename = gammapy_extra.filename('test_datasets/background/bg_cube_model_test2.fits.gz')
        bg_cube_model_1 = CubeBackgroundModel.read(filename, format='table')

        outfile = str(tmpdir / 'cubebackground_table_test.fits')
        bg_cube_model_1.write(outfile, format='table')

        # test if values are correct in the saved file: compare both files
        bg_cube_model_2 = CubeBackgroundModel.read(outfile, format='table')
        cubes1 = [bg_cube_model_1.counts_cube,
                  bg_cube_model_1.livetime_cube,
                  bg_cube_model_1.background_cube]
        cubes2 = [bg_cube_model_2.counts_cube,
                  bg_cube_model_2.livetime_cube,
                  bg_cube_model_2.background_cube]
        for cube1, cube2 in zip(cubes1, cubes2):
            assert_quantity_allclose(cube2.data,
                                     cube1.data)
            assert_quantity_allclose(cube2.coordx_edges,
                                     cube1.coordx_edges)
            assert_quantity_allclose(cube2.coordy_edges,
                                     cube1.coordy_edges)
            assert_quantity_allclose(cube2.energy_edges,
                                     cube1.energy_edges)

    def test_define_binning(self):

        obs_table = ObservationTable()
        obs_table['OBS_ID'] = np.arange(100)
        bg_cube_model = CubeBackgroundModel.define_cube_binning(
            observation_table=obs_table, method='default',
        )

        assert bg_cube_model.background_cube.data.shape == (20, 60, 60)

    @requires_dependency('scipy')
    def test_smooth(self):

        filename = gammapy_extra.filename('test_datasets/background/bg_cube_model_test2.fits.gz')
        bg_cube_model1 = CubeBackgroundModel.read(filename, format='table')

        bg_cube_model2 = bg_cube_model1

        # reset background and fill again
        bg_cube_model2.background_cube.data = np.array([0])
        bg_cube_model2.background_cube.data = bg_cube_model2.counts_cube.data.copy()
        bg_cube_model2.smooth()
        bg_cube_model2.background_cube.data /= bg_cube_model2.livetime_cube.data
        bg_cube_model2.background_cube.data /= bg_cube_model2.background_cube.bin_volume

        # test: the bg should be the same as at the beginning
        assert (bg_cube_model2.background_cube.data == bg_cube_model1.background_cube.data).all()


def make_test_array(empty=True):
    ebounds = EnergyBounds.equal_log_spacing(0.1, 100, 100, 'TeV')
    offset = Angle(np.linspace(0, 2.5, 100), "deg")
    multi_array = EnergyOffsetBackgroundModel(ebounds, offset)
    if not empty:
        multi_array.counts.data.value[:] = 1
        multi_array.livetime.data.value[:] = 2
        multi_array.bg_rate.data.value[:] = 3

    return multi_array


def make_test_array_fillobs(excluded_sources=None, fov_radius=Angle(2.5, "deg")):
    dir = str(gammapy_extra.dir) + '/datasets/hess-crab4-hd-hap-prod2'
    data_store = DataStore.from_dir(dir)
    obs_table = data_store.obs_table
    multi_array = make_test_array()
    multi_array.fill_obs(obs_table, data_store)
    return multi_array


def make_test_array_oneobs(excluded_sources=None, fov_radius=Angle(2.5, "deg")):
    dir = str(gammapy_extra.dir) + '/datasets/hess-crab4-hd-hap-prod2'
    data_store = DataStore.from_dir(dir)
    obs_table = data_store.obs_table
    multi_array = make_test_array()
    multi_array.fill_obs([obs_table[0]], data_store, excluded_sources, fov_radius)
    return multi_array, data_store, obs_table[0]


def make_excluded_sources():
    centers = SkyCoord([1, 0], [2, 1], unit='deg')
    radius = Angle('0.3 deg')
    sources = SkyCircleRegion(pos=centers, radius=radius)
    catalog = Table()
    catalog["RA"] = sources.pos.data.lon
    catalog["DEC"] = sources.pos.data.lat
    catalog["Radius"] = sources.radius
    return catalog


def make_source_nextCrab():
    center = SkyCoord([84, 89], [23, 20], unit='deg', frame='icrs')
    radius = Angle('0.3 deg')
    sources = SkyCircleRegion(pos=center, radius=radius)
    catalog = Table()
    catalog["RA"] = sources.pos.data.lon
    catalog["DEC"] = sources.pos.data.lat
    catalog["Radius"] = sources.radius
    return catalog


def test_compute_pie_fraction():
    excluded_sources = make_excluded_sources()
    pointing_position = SkyCoord(0.5, 0.5, unit='deg')
    # Test that if the sources are out of the fov, it gives a pie_fraction equal to zero
    pie_fraction = _compute_pie_fraction(excluded_sources, pointing_position, Angle(0.3, "deg"))
    assert_allclose(pie_fraction, 0)

    # I have to use an other object excluded_region because the previous one was
    # already sorted in the compute_pie_fraction
    excluded_sources2 = make_excluded_sources()
    source_closest = SkyCoord(excluded_sources2["RA"][1], excluded_sources2["DEC"][1], unit="deg")
    separation = pointing_position.separation(source_closest).value
    pie_fraction = _compute_pie_fraction(excluded_sources, pointing_position, Angle(5, "deg"))
    pie_fraction_expected = (2 * np.arctan(excluded_sources2["Radius"][1] / separation) / (2 * np.pi))
    assert_allclose(pie_fraction, pie_fraction_expected)


def test_select_events_outside_pie():
    """
    Create an empty image centered on the pointing position and all the radec position of the pixels will
    define one event. Thus we create a false EventList with these pixels. We apply the select_events_outside_pie()
    and we fill the image only with the events (pixels) outside the pie. We assert that outside the pie the image is
    fill with 1 and inside with 0.
    """
    excluded_sources = make_excluded_sources()

    pointing_position = SkyCoord(0.5, 0.5, unit='deg')
    events = EventList()
    ra = np.array([0.25, 0.02, 359.3, 1.04, 1.23, 359.56, 359.48])
    dec = np.array([0.72, 0.96, 1.71, 1.05, 0.19, 2.01, 0.24])
    # Faked EventList with the radec of all the pixel in the empty image
    events["RA"] = ra.flat
    events["DEC"] = dec.flat

    # Test that if the sources are out of the fov, it gives the index for all the events since no event will be removed
    idx = _select_events_outside_pie(excluded_sources, events, pointing_position, Angle(0.3, "deg"))
    assert_allclose(np.arange(len(events)), idx)

    # Test if after calling the select_events_outside_pie, the image is 0 inside the pie and 1 outside the pie
    idx = _select_events_outside_pie(excluded_sources, events, pointing_position, Angle(5, "deg"))
    assert_allclose(idx, [3, 4, 6])


@requires_data('gammapy-extra')
class TestEnergyOffsetBackgroundModel:
    def test_read_write(self):
        multi_array = make_test_array(empty=False)
        filename = 'multidata.fits'
        multi_array.write(filename)
        multi_array2 = EnergyOffsetBackgroundModel.read(filename)

        assert_quantity_allclose(multi_array.counts.data, multi_array2.counts.data)
        assert_quantity_allclose(multi_array.livetime.data, multi_array2.livetime.data)
        assert_quantity_allclose(multi_array.bg_rate.data, multi_array2.bg_rate.data)
        assert_quantity_allclose(multi_array.counts.energy, multi_array2.counts.energy)
        assert_quantity_allclose(multi_array.counts.offset, multi_array2.counts.offset)

    def test_fillobs_and_computerate(self):
        multi_array = make_test_array_fillobs()
        multi_array.compute_rate()
        assert_equal(multi_array.counts.data.value.sum(), 5403)
        pix = 23, 1
        assert_quantity_allclose(multi_array.livetime.data[pix], 6313.8117676 * u.s)
        rate = Quantity(0.0024697306536062276, "MeV-1 s-1 sr-1")
        assert_quantity_allclose(multi_array.bg_rate.data[pix], rate)

    def test_fillobs_pie(self):
        """
        Test for one observation of the for Crab for the livetime array and the counts array after applying the pie
        """
        excluded_sources = make_source_nextCrab()
        multi_array1, data_store1, obs_table1 = make_test_array_oneobs(excluded_sources, fov_radius=Angle(2.5, "deg"))
        multi_array2, data_store2, obs_table2 = make_test_array_oneobs()
        events = data_store1.load(obs_table1['OBS_ID'], 'events')

        # Test if the livetime array where we apply the pie is less by the factor pie_fraction of the livetime
        # array where we don't apply the pie
        pie_fraction = _compute_pie_fraction(excluded_sources, events.pointing_radec, Angle(5, "deg"))
        assert_allclose(multi_array1.livetime.data, multi_array2.livetime.data * (1 - pie_fraction))

        # Test if the total counts array where we apply the pie is equal to the number of events outside the pie
        idx = _select_events_outside_pie(excluded_sources, events, events.pointing_radec, Angle(5, "deg"))
        offmax = multi_array1.counts.offset.max()
        # This is important since in the counts array the events > offsetmax will not be in the histogram.
        nevents_sup_offmax = len(np.where(events[idx].offset > offmax)[0])
        assert_allclose(np.sum(multi_array1.counts.data), len(idx) - nevents_sup_offmax)
