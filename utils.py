#!/usr/bin/env python
# encoding: utf-8

import numpy as np
from scipy.special import erf
import string
import hashlib
import collections as c
import time
import logging
from pprint import pformat as pf
import gzip
import os.path as osp
try:
    import cPickle as pickle
except ImportError:
    import pickle

from .logcfg import log


def IF_cond_exp_distribution(rates_exc, rates_inh, weights_exc, weights_inh,
        e_rev_E, e_rev_I, tau_syn_E, tau_syn_I, g_l, v_rest, cm,
        **sink): #sink is just to absorb unused parameter names
    """
    High Conductance State distribution

    Source parameters are expected to be numpy arrays.
    Unit for rates is Hz!

    All parameters are pynn parameters.

    g_l: leak_conductance
    """
    # convert rates to kHz
    rates_exc /= 1000.
    rates_inh /= 1000.

    # calculate exc, inh and total conductance

    g_exc = np.dot(weights_exc, rates_exc) * tau_syn_E
    g_inh = np.dot(weights_inh, rates_inh) * tau_syn_I
    g_tot = g_exc + g_inh + g_l

    # calculate effective (mean) membrane potential and time constant

    tau_eff = cm / g_tot
    v_eff = (e_rev_E * g_exc + e_rev_I * g_inh + v_rest * g_l) / g_tot

    log.info("tau_eff: {:.3f} ms".format(tau_eff))

    ####### calculate variance of membrane potential #######

    tau_g_exc = 1. / (1. / tau_syn_E - 1. / tau_eff)
    tau_g_inh = 1. / (1. / tau_syn_I - 1. / tau_eff)

    S_exc = weights_exc * (e_rev_E - v_eff) * tau_g_exc / tau_eff / g_tot
    S_inh = weights_inh * (e_rev_I - v_eff) * tau_g_inh / tau_eff / g_tot

    var_tau_e = tau_syn_E/2. + tau_eff/2.\
            - 2. * tau_eff * tau_syn_E / (tau_eff + tau_syn_E)

    var_tau_i = tau_syn_I/2. + tau_eff/2.\
            - 2. * tau_eff * tau_syn_I / (tau_eff + tau_syn_I)

    # log.info("v_tau_e/v_tau_i: {} / {}".format(v_tau_e, v_tau_i))

    var = np.dot(rates_exc, S_exc**2) * var_tau_e\
        + np.dot(rates_inh, S_inh**2) * var_tau_i

    return v_eff, np.sqrt(var), g_tot


def IF_curr_exp_distribution(rates_exc, rates_inh, weights_exc, weights_inh,
        v_rest, tau_syn_E, tau_syn_I, g_l, cm,
        **sink): #sink is just to absorb unused parameter names
    """
        Vmem distribution
        Unit for rates is Hz!

        All parameters are pynn parameters.

        g_l : leak conductance in µS
    """
    # convert rates to kHz
    rates_exc /= 1000.
    rates_inh /= 1000.

    # calculate total current and conductance

    I_exc = np.dot(weights_exc, rates_exc) * tau_syn_E
    I_inh = np.dot(weights_inh, rates_inh) * tau_syn_I
    g_tot = g_l

    # calculate effective (mean) membrane potential and time constant #######

    tau_eff = cm / g_tot
    v_eff = (I_exc + I_inh) / g_l + v_rest

    log.info("tau_eff: {:.3f}".format(tau_eff))

    # calculate variance of membrane potential

    tau_g_exc = 1. / (1. / tau_syn_E - 1. / tau_eff)
    tau_g_inh = 1. / (1. / tau_syn_I - 1. / tau_eff)

    S_exc = weights_exc * tau_g_exc / tau_eff / g_tot
    S_inh = weights_inh * tau_g_inh / tau_eff / g_tot

    var = np.dot(rates_exc, S_exc**2)\
            * (tau_syn_E/2. + tau_eff/2.\
                - 2. * tau_eff * tau_syn_E / (tau_eff + tau_syn_E))\
        + np.dot(rates_inh, S_inh**2)\
            * (tau_syn_I/2. + tau_eff/2.\
                - 2. * tau_eff * tau_syn_I / (tau_eff + tau_syn_I))

    return v_eff, np.sqrt(var), g_tot


def sigmoid(x):
    return 1./(1.+np.exp(-x))


def sigmoid_trans(x, x_p05, alpha):
    return 1./(1. + np.exp( -(x-x_p05)/alpha))


def gauss(x, mean, sigma):
    return 1./np.sqrt(2.*np.pi)/np.abs(sigma)*np.exp(-(x-mean)**2/2./sigma**2)


def erfm(x, mean, sigma):
    return .5*(1.+erf((x-mean)/np.sqrt(2.)/np.abs(sigma)))


def get_all_source_parameters(db_sources):
    """
        Returns a tuple of `np.array`s with source configuration
            (rates_exc, rates_inh, weights_exc, weights_inh)
    """

    num_sources = len(db_sources)
    num_sources_exc = len(filter(lambda x: x.is_exc, db_sources))
    num_sources_inh = num_sources - num_sources_exc

    rates_exc = np.empty((num_sources_exc,))
    weights_exc = np.empty((num_sources_exc,))

    rates_inh = np.empty((num_sources_inh,))
    weights_inh = np.empty((num_sources_inh,))

    i_exc = 0
    i_inh = 0

    for src in db_sources:
        if src.is_exc:
            rates_exc[i_exc] = src.rate
            weights_exc[i_exc] = src.weight
            i_exc += 1
        else:
            rates_inh[i_inh] = src.rate
            weights_inh[i_inh] = src.weight
            i_inh += 1

    return rates_exc, rates_inh, weights_exc, weights_inh

def fill_diagonal(array, value=0):
    """
        Fill the diagonal of `array` with `value`.
    """
    # ensure quadratic form
    for s in array.shape:
        assert s == array.shape[0]

    index = np.arange(array.shape[0], dtype=int)

    indices = [index for s in array.shape]

    array[indices] = value

    return array


def get_random_string(n=32, letters=string.ascii_letters):
    return "".join((letters[i] for i in np.random.randint(len(letters),
        size=n)))


def get_sha1(array):
    sha1 = hashlib.sha1()
    sha1.update(array)
    return sha1.hexdigest()


TimeTuple = c.namedtuple("duration", "d h m s ms".split())

# durations in seconds
TIME_DELTAS = TimeTuple(24*3600, 3600, 60, 1, .001)

def make_time_closure_writable(timediff):
    timediff = [timediff]
    def sub(s):
        # closures need mutable objects to write to, but
        # numbers in themselves are immutable
        t = timediff[0]
        timediff[0] = np.mod(t, s)
        return int(np.floor(t/s))
    return sub

def get_time_tuple(timediff):
    return TimeTuple(*map(make_time_closure_writable(timediff), TIME_DELTAS))

def format_time(timediff):
    fmtd = get_time_tuple(timediff)
    return " ".join(
            ("{0}{1}".format(getattr(fmtd, s), s) for s in fmtd._fields
                if getattr(fmtd, s) > 0.))

def get_eta(t_start, current, total):
    """
        Estimate time it takes to finish for simulation of work `total`, if
        the simulation was started at `t_start` and has done work `current`.
    """
    t_elapsed = time.time() - t_start
    if current > 0.:
        return t_elapsed / current * (total - current)
    else:
        return "N/A"

def save_pickle(obj, filename, force_extention=False, compresslevel=9):
    """
        Save object in compressed pickle filename.

        By default the extension of the filename will always be replaced by
        "pkl.gz".
    """

    if not force_extention:
        filename = filename.split(osp.extsep)[0] + ".pkl.gz"

    with gzip.open(filename, "wb", compresslevel=compresslevel) as f:
        pickle.dump(obj, f, protocol=-1)

def load_pickle(filename, force_extension=False):
    """
        Load pickle object from file, if `force_extension` is True, the
        extension will NOT be changed to ".pkl.gz".
    """
    if not force_extension:
        filename = filename.split(osp.extsep)[0] + ".pkl.gz"

    if filename.split(osp.extsep)[-1] == "gz":
        file_opener = gzip.open
    else:
        file_opener = open

    with file_opener(filename) as f:
        return pickle.load(f)

def get_ordered_spike_idx(spiketrains):
    """
        Take spike trains and return a (num_spikes,) record array that contains
        the spike ids ('id') on first and the spike times ('t') on second
        position. The spike times are sorted in ascending order.
    """
    num_spikes = sum((len(st) for st in spiketrains))
    spikes = np.zeros((num_spikes,), dtype=[("id", int), ("t", float)])

    current = 0 

    for i,st in enumerate(spiketrains):
        if log.getEffectiveLevel() <= logging.DEBUG:
            log.debug("Raw spikes for #{}: {}".format(i, pf(st)))
        spikes["id"][current:current+len(st)] = i
        spikes["t"][current:current+len(st)] = np.array(st)

        current += len(st)

    sort_idx = np.argsort(spikes["t"])
    sorted_spikes = spikes[sort_idx].copy()

    return sorted_spikes

def check_list_array(obj):
    return isinstance(obj, c.Sequence) or isinstance(obj, np.ndarray)

