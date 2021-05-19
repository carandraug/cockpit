#!/usr/bin/python
# -*- coding: utf-8

## Copyright (C) 2017 Ian Dobbie <ian.dobbie@bioch.ox.ac.uk>
## Copyright (C) 2018 Nick Hall <nicholas.hall@dtc.ox.ac.uk>
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

"""Cockpit Device file for Deformable Mirror AO device.

This file provides the cockpit end of the driver for a deformable
mirror as currently mounted on DeepSIM in Oxford.

"""

import os.path
import typing
from itertools import groupby

import numpy as np
import scipy.stats
import wx

import cockpit.handlers.executor
from cockpit.devices.device import Device
from cockpit.devices.microscopeDevice import MicroscopeBase
from cockpit.util import userConfig


def remote_ac_fits(
    LUT_array, n_actuators: int
) -> typing.Tuple[np.ndarray, np.ndarray]:
    # For Z positions which have not been calibrated, approximate with
    # a regression of known positions.

    actuator_slopes = np.zeros(n_actuators)
    actuator_intercepts = np.zeros(n_actuators)

    pos = np.sort(LUT_array[:, 0])[:]
    ac_array = np.zeros((np.shape(LUT_array)[0], n_actuators))

    count = 0
    for jj in pos:
        ac_array[count, :] = LUT_array[np.where(LUT_array == jj)[0][0], 1:]
        count += 1

    for kk in range(n_actuators):
        linregress_result = scipy.stats.linregress(pos, ac_array[:, kk])
        actuator_slopes[kk] = linregress_result.slope
        actuator_intercepts[kk] = linregress_result.intercept
    return actuator_slopes, actuator_intercepts


class MicroscopeDeformableMirror(MicroscopeBase, Device):
    def __init__(self, name, config={}):
        super().__init__(name, config)

    def initialize(self):
        super().initialize()
        n_actuators = self._proxy.n_actuators
        self.actuator_slopes = np.zeros(n_actuators)
        self.actuator_intercepts = np.zeros(n_actuators)

        config_dir = wx.GetApp().Config["global"].get("config-dir")

        # Create accurate look up table for certain Z positions LUT
        # dict has key of Z positions.
        try:
            file_path = os.path.join(config_dir, "remote_focus_LUT.txt")
            LUT_array = np.loadtxt(file_path)
            self.LUT = {}
            for ii in (LUT_array[:, 0])[:]:
                self.LUT[ii] = LUT_array[np.where(LUT_array == ii)[0][0], 1:]
        except Exception:
            self.LUT = None

        # Slopes and intercepts are used for extrapolating values not
        # found in the LUT dict.
        if self.LUT is not None:
            self.actuator_slopes, self.actuator_intercepts = remote_ac_fits(
                self.LUT, n_actuators
            )

        # Initiate a table for calibrating the look up table.
        self.remote_focus_LUT = []

    def examineActions(self, table):
        # Extract pattern parameters from the table.
        # patternParms is a list of tuples (angle, phase, wavelength)
        patternParams = [row[2] for row in table if row[1] is self.handler]
        if not patternParams:
            # DM is not used in this experiment.
            return

        # Remove consecutive duplicates and position resets.
        reducedParams = [
            p[0] for p in groupby(patternParams) if isinstance(p[0], float)
        ]
        # Find the repeating unit in the sequence.
        sequenceLength = len(reducedParams)
        for length in range(2, len(reducedParams) // 2):
            if reducedParams[0:length] == reducedParams[length : 2 * length]:
                sequenceLength = length
                break
        sequence = reducedParams[0:sequenceLength]

        # Calculate DM positions
        ac_positions = (
            np.outer(reducedParams, self.actuator_slopes.T)
            + self.actuator_intercepts
        )
        # Queue patterns on DM.
        if ac_positions.size != 0:
            self._proxy.queue_patterns(ac_positions)
        else:
            # No actuator values to queue, so pass
            pass

        # Track sequence index set by last set of triggers.
        lastIndex = 0
        for i, (t, handler, action) in enumerate(table.actions):
            if handler is not self.handler:
                # Nothing to do
                continue
            # Action specifies a target frame in the sequence.
            # Remove original event.
            if isinstance(action, tuple):
                # Don't remove event for tuple.
                # This is the type for remote focus calibration experiment
                pass
            else:
                table[i] = None
            # How many triggers?
            if isinstance(action, float) and action != sequence[lastIndex]:
                # Next pattern does not match last, so step one pattern.
                numTriggers = 1
            elif isinstance(action, int):
                if action >= lastIndex:
                    numTriggers = action - lastIndex
                else:
                    numTriggers = sequenceLength - lastIndex - action
            else:
                numTriggers = 0
            """
            Used to calculate time to execute triggers and settle here,
            then push back all later events, but that leads to very long
            delays before the experiment starts. For now, comment out
            this code, and rely on a fixed time passed back to the action
            table generator (i.e. experiment class).
            # How long will the triggers take?
            # Time between triggers must be > table.toggleTime.
            dt = self.settlingTime + 2 * numTriggers * table.toggleTime
            ## Shift later table entries to allow for triggers and settling.
            table.shiftActionsBack(time, dt)
            for trig in range(numTriggers):
            t = table.addToggle(t, triggerHandler)
            t += table.toggleTime
            """
            for trig in range(numTriggers):
                t = table.addToggle(t, self.handler)
                t += table.toggleTime

            lastIndex += numTriggers
            if lastIndex >= sequenceLength:
                if sequenceLength == 0:
                    pass
                else:
                    lastIndex = lastIndex % sequenceLength
        table.clearBadEntries()
        # Store the parameters used to generate the sequence.
        self.lastParms = ac_positions
        # should add a bunch of spurious triggers on the end to clear the buffer for AO
        for trig in range(12):
            t = table.addToggle(t, self.handler)
            t += table.toggleTime

    def getHandlers(self):
        trigsource = self.config.get("triggersource", None)
        trigline = self.config.get("triggerline", None)
        dt = self.config.get("settlingtime", 10)
        result = []
        self.handler = cockpit.handlers.executor.DelegateTrigger(
            "dm",
            "dm group",
            True,
            {
                "examineActions": self.examineActions,
                "getMovementTime": lambda *args: dt,
                "executeTable": self.executeTable,
            },
        )
        self.handler.delegateTo(trigsource, trigline, 0, dt)
        result.append(self.handler)
        return result

    ## Run a portion of a table describing the actions to perform in a given
    # experiment.
    # \param table An ActionTable instance.
    # \param startIndex Index of the first entry in the table to run.
    # \param stopIndex Index of the entry before which we stop (i.e. it is
    #        not performed).
    # \param numReps Number of times to iterate the execution.
    # \param repDuration Amount of time to wait between reps, or None for no
    #        wait time.
    def executeTable(self, table, startIndex, stopIndex, numReps, repDuration):
        # The actions between startIndex and stopIndex may include actions for
        # this handler, or for this handler's clients. All actions are
        # ultimately carried out by this handler, so we need to parse the
        # table to replace client actions, resulting in a table of
        # (time, self).
        n_actuators = self._proxy.n_actuators

        for t, h, args in table[startIndex:stopIndex]:
            if h is self.handler:
                if isinstance(args, float):
                    # This should have been replaced by a trigger and the entry cleared
                    # Theoretically, this check should always be False
                    pass
                elif isinstance(args, np.ndarray):
                    self._proxy.send(args)
                elif isinstance(args, str):
                    if args[1] == "clean":
                        # Clean any pre-exisitng values from the LUT
                        self.remote_focus_LUT = []
                    else:
                        raise Exception(
                            "Argument Error: Argument type %s not understood."
                            % str(type(args))
                        )
                elif isinstance(args, tuple):
                    if args[1] == "flatten":
                        LUT_values = np.zeros(n_actuators + 1)
                        LUT_values[0] = args[0]
                        LUT_values[1:] = self._proxy.flatten_phase(
                            iterations=5
                        )
                        self._proxy.reset()
                        self._proxy.send(LUT_values[1:])
                        self.remote_focus_LUT.append(
                            np.ndarray.tolist(LUT_values)
                        )
                    else:
                        raise Exception(
                            "Argument Error: Argument type %s not understood."
                            % str(type(args))
                        )
                else:
                    raise Exception(
                        "Argument Error: Argument type %s not understood."
                        % str(type(args))
                    )

        if len(self.remote_focus_LUT) != 0:
            config_dir = wx.GetApp().Config["global"].get("config-dir")
            file_path = os.path.join(config_dir, "remote_focus_LUT.txt")
            np.savetxt(file_path, np.asanyarray(self.remote_focus_LUT))
            userConfig.setValue("dm_remote_focus_LUT", self.remote_focus_LUT)
