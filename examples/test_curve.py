"""Example how to make an acceptance curve and background model image.
"""
from astropy.table import Table
import astropy.units as u
from astropy.io import fits
from astropy.coordinates import SkyCoord, Angle
from astropy.units import Quantity
from gammapy.datasets import gammapy_extra
from gammapy.background import EnergyOffsetBackgroundModel
from gammapy.utils.energy import EnergyBounds, Energy
from gammapy.data import DataStore
from gammapy.utils.axis import sqrt_space
from gammapy.image import bin_events_in_image, make_empty_image, disk_correlate
from gammapy.background import fill_acceptance_image
from gammapy.region import SkyCircleRegion
from gammapy.stats import significance
# from gammapy.detect import compute_ts_map
import pylab as pt

pt.ion()


def make_excluded_sources():
    #centers = SkyCoord([84, 82], [23, 21], unit='deg')
    centers = SkyCoord([83.63, 83.63], [22.01, 22.01], unit='deg', frame='icrs')
    radius = Angle('0.3 deg')
    sources = SkyCircleRegion(pos=centers, radius=radius)
    catalog = Table()
    catalog["RA"] = sources.pos.data.lon
    catalog["DEC"] = sources.pos.data.lat
    catalog["Radius"] = sources.radius
    return catalog


def make_model():
    dir = str(gammapy_extra.dir) + '/datasets/hess-crab4-hd-hap-prod2'
    data_store = DataStore.from_dir(dir)
    obs_table = data_store.obs_table
    ebounds = EnergyBounds.equal_log_spacing(0.1, 100, 100, 'TeV')
    offset = sqrt_space(start=0, stop=2.5, num=100) * u.deg

    excluded_sources = make_excluded_sources()

    multi_array = EnergyOffsetBackgroundModel(ebounds, offset)
    multi_array.fill_obs(obs_table, data_store, excluded_sources)
    #multi_array.fill_obs(obs_table, data_store)
    multi_array.compute_rate()
    bgarray = multi_array.bg_rate
    energy_range = Energy([1, 10], 'TeV')
    table = bgarray.acceptance_curve_in_energy_band(energy_range, energy_bins=10)

    multi_array.write('energy_offset_array.fits', overwrite=True)
    table.write('acceptance_curve.fits', overwrite=True)


def make_image():
    table = Table.read('acceptance_curve.fits')
    table.pprint()
    center = SkyCoord(83.63, 22.01, unit='deg').galactic

    counts_image = make_empty_image(nxpix=1000, nypix=1000, binsz=0.01, xref=center.l.deg, yref=center.b.deg,
                                    proj='TAN')
    bkg_image = counts_image.copy()
    data_store = DataStore.from_dir('$GAMMAPY_EXTRA/datasets/hess-crab4-hd-hap-prod2')

    for events in data_store.load_all("events"):
        center = events.pointing_radec.galactic
        livetime = events.observation_live_time_duration
        solid_angle = Angle(0.01, "deg") ** 2

        counts_image.data += bin_events_in_image(events, counts_image).data

        #interp_param = dict(bounds_error=False, fill_value=None)

        acc_hdu = fill_acceptance_image(bkg_image.header, center, table["offset"], table["Acceptance"])
        acc = Quantity(acc_hdu.data, table["Acceptance"].unit) * solid_angle * livetime
        bkg_image.data += acc.decompose()
        print(acc.decompose().sum())

    counts_image.writeto("counts_image.fits", clobber=True)
    bkg_image.writeto("bkg_image.fits", clobber=True)

    # result = compute_ts_map(counts_stacked_image.data, bkg_stacked_image.data,
    #  maps['ExpGammaMap'].data, kernel)


def make_significance_image():
    counts_image = fits.open("counts_image.fits")[1]
    bkg_image = fits.open("bkg_image.fits")[1]
    counts = disk_correlate(counts_image.data, 10)
    bkg = disk_correlate(bkg_image.data, 10)
    s = significance(counts, bkg)
    s_image = fits.ImageHDU(data=s, header=counts_image.header)
    s_image.writeto("significance_image.fits", clobber=True)



def plot_model():
    multi_array = EnergyOffsetBackgroundModel.read('energy_offset_array.fits')
    table = Table.read('acceptance_curve.fits')
    pt.figure(1)
    multi_array.counts.plot_image()
    pt.figure(2)
    multi_array.livetime.plot_image()
    pt.figure(3)
    multi_array.bg_rate.plot_image()
    pt.figure(4)
    pt.plot(table["offset"], table["Acceptance"])
    pt.xlabel("offset (deg)")
    pt.ylabel("Acceptance (s-1 sr-1)")

    input()


if __name__ == '__main__':
    make_model()
    plot_model()
    make_image()
    make_significance_image()
