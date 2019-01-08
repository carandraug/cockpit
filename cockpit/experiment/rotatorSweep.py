#!/usr/bin/env python
# -*- coding: utf-8 -*-

## Copyright (C) 2018 Mick Phillips <mick.phillips@gmail.com>
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


import decimal

import cockpit.experiment.actionTable
import cockpit.experiment.experiment


class RotatorSweepExperiment(cockpit.experiment.experiment.Experiment):
    def __init__(self, polarizerHandler, settlingTime, startV, maxV, vSteps,
                 exposures, otherHandlers=[], metadata='', savePath=''):

        ## Most of the arguments in the parent are useless to us.
        numReps = 1
        repDuration = None
        zPositioner = None
        z_positions = []
        super(RotatorSweepExperiment, self).__init__(numReps, repDuration,
                                                     zPositioner, z_positions,
                                                     exposures, otherHandlers,
                                                     metadata, savePath)

        self.polarizerHandler = polarizerHandler
        self.settlingTime = settlingTime
        # Look up the rotator analogue line handler.
        self.lineHandler = polarizerHandler
        self.vRange = (startV, maxV, vSteps)
        vDelta = float(maxV - startV) / vSteps
        # Add voltage parameters to the metadata.
        self.metadata = 'Rotator start and delta: [%f, %f]' % (startV, vDelta)


    ## Create the ActionTable needed to run the experiment.
    def generateActions(self):
        table = cockpit.experiment.actionTable.ActionTable()
        curTime = 0
        vStart, vLessThan, vSteps = self.vRange
        dv = float(vLessThan - vStart) / float(vSteps)
        dt = decimal.Decimal(self.settlingTime)

        for step in range(vSteps):
            # Move to next polarization rotator voltage.
            vTarget = vStart + step * dv
            table.addAction(curTime, self.lineHandler, vTarget)
            curTime += dt
            # Image the sample.
            for exposure in self.exposures:
                curTime = self.expose(curTime, exposure, table)
                # Advance the time very slightly so that all exposures
                # are strictly ordered.
                curTime += decimal.Decimal('.001')
            # Hold the rotator angle constant during the exposure.
            table.addAction(curTime, self.lineHandler, vTarget)
            # Advance time slightly so all actions are sorted (e.g. we
            # don't try to change angle and phase in the same timestep).
            curTime += dt

        return table
