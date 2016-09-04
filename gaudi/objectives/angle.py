#!/usr/bin/env python
# -*- coding: utf-8 -*-

##############
# GAUDIasm: Genetic Algorithms for Universal
# Design Inference and Atomic Scale Modeling
# Authors:  Jaime Rodriguez-Guerra Pedregal
#            <jaime.rodriguezguerra@uab.cat>
#           Jean-Didier Marechal
#            <jeandidier.marechal@uab.cat>
# Web: https://bitbucket.org/jrgp/gaudi
##############

"""
This objective calculates the angle formed by three
given atoms (or the dihedral, if four atoms are given) and returns
the absolute difference of that angle and the target value.

"""

# Python
from __future__ import print_function
import math
import logging
# Chimera
import chimera
# GAUDI
from gaudi.objectives import ObjectiveProvider
from gaudi import parse

logger = logging.getLogger(__name__)


def enable(**kwargs):
    kwargs = Angle.validate(kwargs)
    return Angle(**kwargs)


class Angle(ObjectiveProvider):

    """
    Angle class

    Parameters
    ----------
    threshold : float
        Optimum angle
    tolerance :
        Allowed difference
    probes : list of str
        Atoms that make the angle, expressed as a series of 
        <molecule_name>/<serial_number> strings
    """

    validate = parse.Schema({
        parse.Required('probes'): parse.AssertList(parse.Named_spec("molecule", "atom")),
        parse.Required('threshold'): parse.Any(parse.Coerce(float), parse.In(['planar']))
        }, extra=parse.ALLOW_EXTRA)

    def __init__(self, threshold=None, probes=None, *args, **kwargs):
        ObjectiveProvider.__init__(self, **kwargs)
        self.threshold = threshold
        self._probes = probes

    def probes(self, ind):
        for probe in self._probes:
            mol, serial = probe
            try:
                atom = next(a for a in ind.genes[mol].compound.mol.atoms if serial == a.serialNumber)
            except StopIteration:
                logger.exception("No atoms matched for probe %s", probe)
                raise
            else:
                yield atom

    def evaluate(self, ind):
        atoms_coords = [a.xformCoord() for a in self.probes(ind)]
        delta = 180.0
        try:
            angle = chimera.angle(*atoms_coords)
        except TypeError:  # four atoms, means dihedral
            angle = chimera.dihedral(*atoms_coords)
        
        if self.threshold == 'planar':
            return abs(math.sin(math.radians(angle)))
        return abs(self.threshold - angle.real)



# TODO: Probes get lost if rotamers are applied!
