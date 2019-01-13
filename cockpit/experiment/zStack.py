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

## Copyright 2013, The Regents of University of California
##
## Redistribution and use in source and binary forms, with or without
## modification, are permitted provided that the following conditions
## are met:
##
## 1. Redistributions of source code must retain the above copyright
##   notice, this list of conditions and the following disclaimer.
##
## 2. Redistributions in binary form must reproduce the above copyright
##   notice, this list of conditions and the following disclaimer in
##   the documentation and/or other materials provided with the
##   distribution.
##
## 3. Neither the name of the copyright holder nor the names of its
##   contributors may be used to endorse or promote products derived
##   from this software without specific prior written permission.
##
## THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
## "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
## LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
## FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
## COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
## INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
## BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
## LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
## CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
## LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
## ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
## POSSIBILITY OF SUCH DAMAGE.


import decimal
import math

import cockpit.experiment
import cockpit.experiment.actionTable
import cockpit.experiment.experiment


class ZStackExperiment(cockpit.experiment.experiment.Experiment):
    """This class handles classic Z-stack experiments.
    """
    ## Create the ActionTable needed to run the experiment. We simply move to
    # each Z-slice in turn, take an image, then move to the next.
    def generateActions(self):
        table = cockpit.experiment.actionTable.ActionTable()
        curTime = 0
        prevAltitude = None

        z_handler_positions = cockpit.experiment.z_stage_to_handler_positions(self.zPositioner,
                                                                              self.z_positions)
        for zTarget in z_handler_positions:
            # Move to the next position, then wait for the stage to
            # stabilize.
            motionTime, stabilizationTime = 0, 0
            if prevAltitude is not None:
                motionTime, stabilizationTime = self.zPositioner.getMovementTime(prevAltitude, zTarget)
            curTime += motionTime
            table.addAction(curTime, self.zPositioner, zTarget)
            curTime += stabilizationTime
            prevAltitude = zTarget

            # Image the sample.
            for exposure in self.exposures:
                curTime = self.expose(curTime, exposure, table)
                # Advance the time very slightly so that all exposures
                # are strictly ordered.
                curTime += decimal.Decimal('1e-10')

            # Hold the Z motion flat during the exposure.
            table.addAction(curTime, self.zPositioner, zTarget)

        # Move back to the start so we're ready for the next rep.
        motionTime, stabilizationTime = self.zPositioner.getMovementTime(
                z_handler_positions[-1], z_handler_positions[0])
        curTime += motionTime
        table.addAction(curTime, self.zPositioner, z_handler_positions[0])
        # Hold flat for the stabilization time, and any time needed for
        # the cameras to be ready. Only needed if we're doing multiple
        # reps, so we can proceed immediately to the next one.
        cameraReadyTime = 0
        if self.numReps > 1:
            for exposure in self.exposures:
                for camera in exposure.cameras:
                    cameraReadyTime = max(cameraReadyTime,
                            self.getTimeWhenCameraCanExpose(table, camera))
        table.addAction(max(curTime + stabilizationTime, cameraReadyTime),
                        self.zPositioner, z_handler_positions[0])

        return table
