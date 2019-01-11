#!/usr/bin/env python
# -*- coding: utf-8 -*-

## Copyright (C) 2018 David Miguel Susano Pinto <david.pinto@bioch.ox.ac.uk>
##
## This file is part of Cockpit.
##
## Cockpit is free software: you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation, either version 3 of the License, or
## (at your option) any later version.
##
## Cockpit is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with Cockpit.  If not, see <http://www.gnu.org/licenses/>.


import abc
import enum
import math

import numpy
import six

from cockpit.experiment.experiment import Experiment
from cockpit.experiment.actionTable import ActionTable


class ActionTable:
    def __init__(self):
        self._actions = []

    def interleave(self, other):
        for i in range(len(self._actions)):
            self._actions.insert(i*2 +2, other)


class Action(six.with_metaclass(abc.ABCMeta)):
    pass


class ZMovement(Action):
    ## should this include the z handler for the movement?
    def __init__(self, position):
        self._position = position


class AbstractExperiment(six.with_metaclass(abc.ABCMeta)):
    @abc.abstractmethod
    def run(self):
        raise NotImplementedError()


class WidefieldExperiment(AbstractExperiment):
    """Basic widefield experiment for 5 dimensions.

    Args:
        z_positions (list of Number): altitude of stage for each
            acquisition
        exposures (list of ExposureSettings): description of how to
            take images
        timepoints (list of Number): time since the start of the
            experiment for each image, where a single image may be
            multiple z and channels.
        z_positioner (StagePositioner): handler to use to move in Z.
        save_path (str): Path to save image data to. If this isn't
            provided then no data will be saved.

    XXX: should savePath may be part of the run, or some other method.
    This would allow us to reuse an experiment, since the save path is
    only done then.

    """
    def __init__(self, z_positions, exposures, timepoints, z_positioner,
                 save_path):
        self._action_table = ActionTable()


## The issue here is that an experiment only happens in one site and
## only one experiment is running at a single time.  But if we have
## multiple sites, we may image in one place (experiment 1), move to
## another site to image (experiment 2), and then go back to the
## previous site to image again (experiment 1) again.  This is a multi
## site experiment all right, but that's just a specific case of
## concurrent experiments.
##
## Alternatively, we can say that it's all one experiment, and that
## multisite is just another type of experiment.  That seems to not be
## the cockpit model of experiment.

class MultiSiteExperiment(object):
    ## TODO: consider instead having a ConcurrentExperiments class or
    ## SynchronizedExperiments
    def __init__(self, experiment, sites):
        pass


def compute_z_positions(start, stack_height, step):
    if stack_height < 0:
        raise ValueError("'stack_height' must be non-negative")

    try:
        num_slices = math.ceil(stack_height / abs(float(step))) +1
    except ZeroDivisionError:
        if stack_height != 0: # we can ignore the error if stack is zero
            raise ValueError("'step' must be non-zero")
        num_slices = 1

    ## Multiply step by index, instead of adding step to previous
    ## iteration, to avoid floating point errors.
    ## Python2: ensure it's an int for python 2 compatibility.
    return [start + i * step for i in range(int(num_slices))]


class ExposureSettings:
    """Exposure Settings for acquisitions that should happen simultaneously.
    """
    def __init__(self):
        self.cameras = set()
        self.exposures = {}

    def add_camera(self, camera):
        self.cameras.add(camera)

    def add_light(self, light, time):
        if light in self.exposures:
            raise ValueError("already time for light '%s'" % str(light))
        self.exposures[light] = time

    def longest_exposure(self):
        """
        Will return `0` if there are no lights.
        """
        try:
            return max(self.exposures.values())
        except ValueError:
            if len(self.exposures.values()) == 0:
                return 0.0
            else:
                raise

    def copy(self):
        """Return a shallow copy.
        """
        copy = ExposureSettings()
        copy.cameras = self.cameras.copy()
        copy.exposures = self.exposures.copy()
        return copy

    def __eq__(self, other):
        return (self.cameras == other.cameras
                and self.exposures == other.exposures)

    def __ne__(self, other):
        ## XXX: this is only required for Python 2.  When we only
        ## support Python 3, this is implicit.
        return not self == other

    ## XXX: Not sure about this static methods to handle sequences.
    ## We could have a list<ExposureSettings> specialisation by
    ## subclassing MutableSequence.

    @staticmethod
    def all_cameras(sequence):
        """All cameras used in a sequence of :class:`ExposureSettings`.
        """
        return set().union(*[x.cameras for x in sequence])

    @staticmethod
    def all_lights(sequence):
        """All lights used in a sequence of :class:`ExposureSettings`.
        """
        return set().union(*[set(x.exposures.keys()) for x in sequence])
