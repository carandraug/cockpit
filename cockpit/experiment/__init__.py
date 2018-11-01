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

from cockpit.experiment.experiment import Experiment

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
