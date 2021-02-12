#!/usr/bin/env python
# -*- coding: utf-8 -*-

## Copyright (C) 2015 Thomas Parks <thomasparks@outlook.com>
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
import math

import wx

from cockpit.gui.guiUtils import tryParseNum
from cockpit import depot, events
from cockpit.experiment.experiment import Experiment
from cockpit.experiment.actionTable import ActionTable


EXPERIMENT_NAME = "STORM"


class STORM(Experiment):
    # TODO: this experiment class is very similar to (actually, it's
    # most copypaste from) the zStackExperiment.  We should clear the
    # code so we could share most of code instead of duplicate it.
    def __init__(self, repetitions=1, sequences=[], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.repetitions = repetitions
        self.sequences = sequences

    # Create the ActionTable needed to run the experiment.  We simply
    # move to each Z-slice in turn, take all the images required for
    # STORM, and move the the next.
    def generateActions(self):
        table = ActionTable()
        curTime = 0
        prevAltitude = None
        numZSlices = int(math.ceil(self.zHeight / self.sliceHeight))
        if self.zHeight > 1e-6:
            # Non-2D experiment; tack on an extra image to hit the top
            # of the volume.
            numZSlices += 1
        for zIndex in range(numZSlices):
            # Move to the next position, then wait for the stage to
            # stabilize.
            targetAltitude = self.sliceHeight * zIndex
            motionTime, stabilizationTime = 0, 0
            if prevAltitude is not None:
                (
                    motionTime,
                    stabilizationTime,
                ) = self.zPositioner.getMovementTime(
                    prevAltitude, targetAltitude
                )
            table.addAction(
                curTime + motionTime, self.zPositioner, targetAltitude
            )
            curTime += motionTime + stabilizationTime
            prevAltitude = targetAltitude

            # Image the sample.
            for rep in range(self.repetitions):
                # A sequence corresponds to a row in the experiment
                #  dialog consists of the required light, the exposure
                #  time, and the camera to use.  We create cameras,
                #  lighttimepairs from this.
                for sequence in self.sequences:
                    print(self.cameraToIsReady, self.sequences)
                    cameras = [sequence[2]]
                    lightTimePairs = [(sequence[0], sequence[1])]

                    curTime = self.expose(
                        curTime, cameras, lightTimePairs, table
                    )
                    # Advance the time very slightly so that all
                    # exposures are strictly ordered.
                    curTime += decimal.Decimal("1e-10")
                    # Hold the Z motion flat during the exposure.
                    table.addAction(curTime, self.zPositioner, targetAltitude)

        # Move back to the start so we're ready for the next rep.
        motionTime, stabilizationTime = self.zPositioner.getMovementTime(
            self.zHeight, 0
        )
        curTime += motionTime
        table.addAction(curTime, self.zPositioner, 0)
        # Hold flat for the stabilization time, and any time needed
        # for the cameras to be ready.  Only needed if we're doing
        # multiple reps, so we can proceed immediately to the next
        # one.
        cameraReadyTime = 0
        if self.numReps > 1:
            for cameras, lightTimePairs in self.exposureSettings:
                for camera in cameras:
                    cameraReadyTime = max(
                        cameraReadyTime,
                        self.getTimeWhenCameraCanExpose(table, camera),
                    )
        table.addAction(
            max(curTime + stabilizationTime, cameraReadyTime),
            self.zPositioner,
            0,
        )

        return table


EXPERIMENT_CLASS = STORM


class inputRow:
    def __init__(self, parent, sizer):
        """Class representing the selections for the STORM experiment plan."""
        self.parent = parent
        self.sizer = sizer
        # The user could change the enabled cameras whilst we are in
        # the Experiment dialog, changing the indices.  This would
        # cause the cameras that were used to be random - V. suprising
        # So, save the enabled cameras as they were when experiment
        # panel opened.
        self.cameras = depot.getActiveCameras()

    def addInputRowToSizer(self):
        self.lightChoice = wx.Choice(
            self.parent,
            choices=[
                str(light.wavelength)
                for light in depot.getHandlersOfType(depot.LIGHT_TOGGLE)
            ],
        )
        self.sizer.Add(self.lightChoice)

        self.PulseLenBox = wx.TextCtrl(self.parent)
        self.sizer.Add(self.PulseLenBox)

        self.camChoice = wx.Choice(
            self.parent,
            choices=[camera.descriptiveName for camera in self.cameras]
            + [str(None)],
        )
        self.sizer.Add(self.camChoice)

        self.enabled = wx.CheckBox(self.parent)
        self.sizer.Add(self.enabled)

        events.subscribe(events.CAMERA_ENABLE, self.cameraToggled)

    def getSelections(self):
        if self.enabled.GetValue():
            light = depot.getHandlersOfType(depot.LIGHT_TOGGLE)[
                self.lightChoice.GetCurrentSelection()
            ]
            exposureLen = int(self.PulseLenBox.GetValue())
            camera = (
                self.cameras[self.camChoice.GetCurrentSelection()]
                if self.camChoice.GetCurrentSelection() != "None"
                else None
            )

            return (light, exposureLen, camera)
        else:
            return None

    def cameraToggled(self, camera, enabled):
        cameraLabel = camera.descriptiveName
        position = self.camChoice.FindString(cameraLabel)
        # Present and now disabled
        if not enabled and position != wx.NOT_FOUND:
            # Remove it
            self.camChoice.Delete(position)
        # Not in the list and enabled
        elif enabled and position == wx.NOT_FOUND:
            self.camChoice.Append(cameraLabel)
        # Update self.cameras as they may have been enabled/disabled since
        # the control was __init__'ed.
        self.cameras = depot.getActiveCameras()


class ExperimentUI(wx.Panel):
    def __init__(self, parent, configKey):
        """Creates a experiment control panel for the STORM class.

        Has one text box for the number of table repetitions to
        execute, and rows (inputRow) that will be executed in order
        numReps times.

        """
        super().__init__(parent=parent)
        self.configKey = configKey
        self.numInputRows = 5
        # List of STORM sequences to add to actiontable.
        # STORM sequence: (numReps, {LIGHT:(duration, camera)})
        self.Sequences = []
        self.regenInput()

    # Everything expects 4 cols.
    def regenInput(self):
        rows = 3 + self.numInputRows
        self.GlobalSizer = wx.FlexGridSizer(rows, 4, 5, 5)

        self.addRepsRow(self.GlobalSizer)
        self.addTitleRow(self.GlobalSizer)

        self.rows = [
            inputRow(parent=self, sizer=self.GlobalSizer)
            for _ in range(self.numInputRows)
        ]
        for row in self.rows:
            pass
            row.addInputRowToSizer()

        self.GlobalSizer.Layout()
        self.SetSizerAndFit(self.GlobalSizer)

    def addRepsRow(self, sizer):
        pass
        sizer.Add(wx.StaticText(self, wx.ID_ANY, "Number of table repeats"))

        self.repsBox = wx.TextCtrl(self)
        sizer.Add(self.repsBox)

        # Placeholders
        sizer.Add(wx.StaticText(self, wx.ID_ANY, ""))
        sizer.Add(wx.StaticText(self, wx.ID_ANY, ""))

    def addTitleRow(self, sizer):
        sizer.Add(wx.StaticText(self, wx.ID_ANY, "Light"))
        sizer.Add(wx.StaticText(self, wx.ID_ANY, "Exposure Length"))
        sizer.Add(wx.StaticText(self, wx.ID_ANY, "Camera to expose with"))
        sizer.Add(wx.StaticText(self, wx.ID_ANY, "Enabled"))

    def augmentParams(self, params):
        sequences = [
            row.getSelections()
            for row in self.rows
            if row.getSelections() is not None
        ]
        params["sequences"] = sequences
        params["repetitions"] = tryParseNum(self.repsBox, int)
        return params
