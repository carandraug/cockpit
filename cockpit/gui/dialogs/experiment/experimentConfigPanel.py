#!/usr/bin/env python
# -*- coding: utf-8 -*-

## Copyright (C) 2018 Mick Phillips <mick.phillips@gmail.com>
## Copyright (C) 2018 Ian Dobbie <ian.dobbie@bioch.ox.ac.uk>
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


from cockpit import depot
import cockpit.experiment.experimentRegistry
from cockpit.gui import guiUtils
import cockpit.gui.saveTopBottomPanel
import cockpit.interfaces.stageMover
import cockpit.util.logger
import cockpit.util.userConfig
import cockpit.util.user

import collections
import decimal
import json
import os
import time
import traceback
import wx

from six import iteritems

## This class provides a GUI for setting up and running experiments, in the
# form of an embeddable wx.Panel and a selection of functions. To use the
# panel, create an instance of ExperimentConfigPanel and insert it into your
# GUI. Call its runExperiment function when you are ready to start the
# experiment.
#
# The parent is required to implement onExperimentPanelResize so that changes
# in the panel size will be handled properly.
class ExperimentConfigPanel(wx.Panel):
    ## Instantiate the class. Pull default values out of the config file, and
    # create the UI and layout.
    # \param resizeCallback Function to call when we have changed size.
    # \param resetCallback Function to call to force a reset of the panel.
    # \param configKey String used to look up settings in the user config. This
    #        allows different experiment panels to have different defaults.
    # \param shouldShowFileControls True if we want to show the file suffix
    #        and filename controls, False otherwise (typically because we're
    #        encapsulated by some other system that handles its own filenames).
    def __init__(self, parent, resizeCallback, resetCallback,
            configKey = 'singleSiteExperiment', shouldShowFileControls = True):
        wx.Panel.__init__(self, parent, style = wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.TAB_TRAVERSAL)
        self.parent = parent

        self.configKey = configKey
        self.resizeCallback = resizeCallback
        self.resetCallback = resetCallback

        ## cockpit.experiment.Experiment subclass instance -- mostly preserved for
        # debugging, so we can examine the state of the experiment.
        self.runner = None

        self.allLights = depot.getHandlersOfType(depot.LIGHT_TOGGLE)
        self.allLights.sort(key = lambda l: l.wavelength)
        self.allCameras = depot.getHandlersOfType(depot.CAMERA)
        self.allCameras.sort(key = lambda c: c.name)

        ## Map of default settings as loaded from config.
        self.settings = self.loadConfig()

        self.SetSizer(wx.BoxSizer(wx.VERTICAL))
        self.sizer = self.GetSizer()

        # Section for settings that are universal to all experiment types.
        universalSizer = wx.FlexGridSizer(1, 3, 5, 5)

        ## Maps experiment description strings to experiment modules.
        self.experimentStringToModule = collections.OrderedDict()
        for module in cockpit.experiment.experimentRegistry.getExperimentModules():
            self.experimentStringToModule[module.EXPERIMENT_NAME] = module

        self.experimentType = wx.Choice(self,
                choices = list(self.experimentStringToModule.keys()) )
        self.experimentType.SetSelection(0)
        guiUtils.addLabeledInput(self, universalSizer,
                label = "Experiment type:", control = self.experimentType)

        self.numReps = guiUtils.addLabeledInput(self,
                universalSizer, label = "Number of reps:",
                defaultValue = self.settings['numReps'])
        self.numReps.SetValidator(guiUtils.INTVALIDATOR)

        self.repDuration = guiUtils.addLabeledInput(self,
                universalSizer, label = "Rep duration (s):",
                defaultValue = self.settings['repDuration'],
                helperString = "Amount of time that must pass between the start " +
                "of each rep. Use 0 if you don't want any wait time.")
        self.repDuration.SetValidator(guiUtils.FLOATVALIDATOR)
        self.sizer.Add(universalSizer, 0, wx.ALL, border=5)

        z_stack_settings = (
            'stackHeight',
            'sliceHeight',
        )
        self.z_stack_panel = ZStackPanel(self,
                                         settings={k:self.settings[k] for k in z_stack_settings})
        self.sizer.Add(self.z_stack_panel, flag=wx.ALL, border=5)

        ## Maps experiment modules to ExperimentUI instances holding the
        # UI for that experiment, if any.
        self.experimentModuleToPanel = {}
        for module in self.experimentStringToModule.values():
            if not hasattr(module, 'ExperimentUI'):
                # This experiment type has no special UI to set up.
                continue
            panel = module.ExperimentUI(self, self.configKey)
            panel.Hide()
            self.sizer.Add(panel)
            self.experimentModuleToPanel[module] = panel
        self.experimentType.Bind(wx.EVT_CHOICE, self.onExperimentTypeChoice)
        self.onExperimentTypeChoice()

        ## TODO: Instead of this, self.settings['exposure'] should return a
        ## dict with the exposure related settings.
        exposure_settings = (
            'simultaneousExposureTimes',
            'shouldExposeSimultaneously',
            'sequencedExposureSettings',
        )
        self.exposure_panel = ExposurePanel(self, self.allLights, self.allCameras,
                                            settings={k:self.settings[k] for k in exposure_settings})
        self.GetSizer().Add(self.exposure_panel.GetSizer())

        self.files_panel = FileLocationPanel(self, suffix=self.settings['filenameSuffix'])
        self.GetSizer().Add(self.files_panel, flag=wx.LEFT)
        self.files_panel.Show(shouldShowFileControls)

        # Save/load experiment settings buttons.
        saveLoadPanel = wx.Panel(self)
        rowSizer = wx.BoxSizer(wx.HORIZONTAL)
        saveButton = wx.Button(saveLoadPanel, -1, "Save experiment settings...")
        saveButton.Bind(wx.EVT_BUTTON, self.onSaveExperiment)
        rowSizer.Add(saveButton, 0, wx.ALL, 5)
        loadButton = wx.Button(saveLoadPanel, -1, "Load experiment settings...")
        loadButton.Bind(wx.EVT_BUTTON, self.onLoadExperiment)
        rowSizer.Add(loadButton, 0, wx.ALL, 5)
        saveLoadPanel.SetSizerAndFit(rowSizer)
        self.sizer.Add(saveLoadPanel, 0, wx.LEFT, 5)

        self.GetSizer().SetSizeHints(self)


    ## Load values from config, and validate them -- since devices may get
    # changed out from under us, rendering some config entries (e.g. dealing
    # with light sources) invalid.
    def loadConfig(self):
        result = cockpit.util.userConfig.getValue(self.configKey, default = {
                'filenameSuffix': '',
                'numReps': '1',
                'repDuration': '0',
                'sequencedExposureSettings': [['' for l in self.allLights] for c in self.allCameras],
                'shouldExposeSimultaneously': True,
                'simultaneousExposureTimes': ['' for l in self.allLights],
                'sliceHeight': '.15',
                'stackHeight': '4',
                'ZPositionMode': 0,
            }
        )
        for key in ['simultaneousExposureTimes']:
            if len(result[key]) != len(self.allLights):
                # Number of light sources has changed; invalidate the config.
                result[key] = ['' for light in self.allLights]
        key = 'sequencedExposureSettings'
        if (len(result[key]) != len(self.allCameras) or
                len(result[key][0]) != len(self.allLights)):
            # Number of lights and/or number of cameras has changed.
            result[key] = [['' for l in self.allLights] for c in self.allCameras]
        return result


    ## User selected a different experiment type; show/hide specific
    # experiment parameters as appropriate; depending on experiment type,
    # some controls may be enabled/disabled.
    def onExperimentTypeChoice(self, event = None):
        newType = self.experimentType.GetStringSelection()
        for expString, module in iteritems(self.experimentStringToModule):
            if module in self.experimentModuleToPanel:
                # This experiment module has a special UI panel which needs
                # to be shown/hidden.
                panel = self.experimentModuleToPanel[module]
                panel.Show(expString == newType)
                panel.Enable(expString == newType)
        self.SetSizerAndFit(self.sizer)
        self.resizeCallback(self)


    ## User clicked the "Save experiment settings..." button; save the
    # parameters for later use as a JSON dict.
    def onSaveExperiment(self, event = None):
        settings = self.getSettingsDict()
        # Augment the settings with information pertinent to our current
        # experiment.
        experimentType = self.experimentType.GetStringSelection()
        settings['experimentType'] = experimentType
        module = self.experimentStringToModule[experimentType]
        if module in self.experimentModuleToPanel:
            # Have specific parameters for this experiment type; store them
            # too.
            settings['experimentSpecificValues'] = self.experimentModuleToPanel[module].getSettingsDict()

        # Get the filepath to save settings to.
        dialog = wx.FileDialog(self, style = wx.FD_SAVE, wildcard = '*.txt',
                message = 'Please select where to save the experiment.',
                defaultDir = cockpit.util.user.getUserSaveDir())
        if dialog.ShowModal() != wx.ID_OK:
            # User cancelled.
            return
        filepath = dialog.GetPath()
        handle = open(filepath, 'w')
        try:
            handle.write(json.dumps(settings))
        except Exception as e:
            cockpit.util.logger.log.error("Couldn't save experiment settings: %s" % e)
            cockpit.util.logger.log.error(traceback.format_exc())
            cockpit.util.logger.log.error("Settings are:\n%s" % str(settings))
        handle.close()


    ## User clicked the "Load experiment settings..." button; load the
    # parameters from a file.
    def onLoadExperiment(self, event = None):
        dialog = wx.FileDialog(self, style = wx.FD_OPEN, wildcard = '*.txt',
                message = 'Please select the experiment file to load.',
                defaultDir = cockpit.util.user.getUserSaveDir())
        if dialog.ShowModal() != wx.ID_OK:
            # User cancelled.
            return
        filepath = dialog.GetPath()
        handle = open(filepath, 'r')
        settings = json.loads(' '.join(handle.readlines()))
        handle.close()
        experimentType = settings['experimentType']
        experimentIndex = self.experimentType.FindString(experimentType)
        module = self.experimentStringToModule[experimentType]
        if module in self.experimentModuleToPanel:
            panel = self.experimentModuleToPanel[module]
            panel.saveSettings(settings['experimentSpecificValues'])
            del settings['experimentSpecificValues']
        cockpit.util.userConfig.setValue(self.configKey, settings)
        # Reset the panel, destroying us and creating a new panel with
        # the proper values in all parameters, except for experiment type.
        panel = self.resetCallback()
        panel.experimentType.SetSelection(experimentIndex)
        panel.onExperimentTypeChoice()


    ## Run the experiment per the user's settings.
    def runExperiment(self):
        # Returns True to close dialog box, None or False otherwise.
        self.saveSettings()
        # Find the Z mover with the smallest range of motion, assumed
        # to be our experiment mover.
        mover = depot.getSortedStageMovers()[2][-1]
        # Only use active cameras and enabled lights.
        # Must do list(filter) because we will iterate over the list
        # many times.
        cameras = list(filter(lambda c: c.getIsEnabled(),
                depot.getHandlersOfType(depot.CAMERA)))
        if not cameras:
            wx.MessageDialog(self,
                    message = "No cameras are enabled, so the experiment cannot be run.",
                    style = wx.ICON_EXCLAMATION | wx.STAY_ON_TOP | wx.OK).ShowModal()
            return True
        lights = list(filter(lambda l: l.getIsEnabled(),
                depot.getHandlersOfType(depot.LIGHT_TOGGLE)))

        exposure_settings = self.exposure_panel.GetExposureSettings(cameras)

        altitude = cockpit.interfaces.stageMover.getPositionForAxis(2)
        # Default to "current is bottom"
        altBottom = altitude
        zHeight = self.z_stack_panel.GetStackHeight()
        if self.z_stack_panel.GetPositionModeText() == 'Current is center':
            altBottom = altitude - zHeight / 2
        elif self.z_stack_panel.GetPositionModeText() == 'Use saved top/bottom':
            altBottom, altTop = cockpit.gui.saveTopBottomPanel.getBottomAndTop()
            zHeight = altTop - altBottom

        sliceHeight = self.z_stack_panel.GetSliceHeight()
        if zHeight == 0:
            # 2D mode.
            zHeight = 1e-6
            sliceHeight = 1e-6

        savePath = os.path.join(cockpit.util.user.getUserSaveDir(),
                                self.files_panel.GetFilename())
        params = {
                'numReps': guiUtils.tryParseNum(self.numReps),
                'repDuration': guiUtils.tryParseNum(self.repDuration, float),
                'zPositioner': mover,
                'altBottom': altBottom,
                'zHeight': zHeight,
                'sliceHeight': sliceHeight,
                'cameras': cameras,
                'lights': lights,
                'exposureSettings': exposure_settings,
                'savePath': savePath
        }
        experimentType = self.experimentType.GetStringSelection()
        module = self.experimentStringToModule[experimentType]
        if module in self.experimentModuleToPanel:
            # Add on the special parameters needed by this experiment type.
            params = self.experimentModuleToPanel[module].augmentParams(params)

        self.runner = module.EXPERIMENT_CLASS(**params)
        return self.runner.run()


    ## Generate a dict of our current settings.
    def getSettingsDict(self):
        newSettings = {
                'filenameSuffix': self.files_panel.GetSuffix(),
                'numReps': self.numReps.GetValue(),
                'repDuration': self.repDuration.GetValue(),
                'sequencedExposureSettings': self.exposure_panel.GetSequencedExposureTimes(),
                'shouldExposeSimultaneously': self.exposure_panel.ShouldExposeSimultaneously(),
                'simultaneousExposureTimes': self.exposure_panel.GetSimultaneousExposureTimes(),
                'sliceHeight': self.z_stack_panel.GetSliceHeight(),
                'stackHeight': self.z_stack_panel.GetStackHeight(),
                'ZPositionMode': self.z_stack_panel.GetPositionMode(),
        }
        return newSettings


    ## Save the current experiment settings to config.
    def saveSettings(self):
        cockpit.util.userConfig.setValue(self.configKey, self.getSettingsDict())


#class ZPanel
class ZStackPanel(wx.Panel):
    ## TODO: this should be an enum somewhere on cockpit.experiment.
    ## Here, we should instead have a map of those enums to the name
    ## to be displayed.
    POSITION_MODES = [
        'Current is center',
        'Current is bottom',
        'Use saved top/bottom'
    ]
    def __init__(self, parent, settings, *args, **kwargs):
        super(ZStackPanel, self).__init__(parent, *args, **kwargs)
        sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.position_choice = wx.Choice(self, choices=self.POSITION_MODES)
        self.position_choice.SetSelection(0) # TODO: this should be in settings

        guiUtils.addLabeledInput(self, sizer, label="Z position mode:",
                                 control=self.position_choice)

        print(settings)
        self.stackHeight = guiUtils.addLabeledInput(self,
                sizer, label = u"Stack height (\u03bcm):",
                defaultValue = str(settings['stackHeight']))
        self.stackHeight.SetValidator(guiUtils.FLOATVALIDATOR)

        self.sliceHeight = guiUtils.addLabeledInput(self,
                sizer, label = u"Slice height (\u03bcm):",
                defaultValue = str(settings['sliceHeight']))
        self.sliceHeight.SetValidator(guiUtils.FLOATVALIDATOR)

        self.SetSizerAndFit(sizer)

    def GetPositionModeText(self):
        ## XXX this should not exist, because there's no promise on
        ## the text actually used.
        return self.position_choice.GetStringSelection()

    def GetPositionMode(self):
        ## TODO this should return an enum.
        return self.position_choice.GetSelection()

    def GetStackHeight(self):
        return float(self.stackHeight.GetValue())

    def GetSliceHeight(self):
        return float(self.sliceHeight.GetValue())


class FileLocationPanel(wx.Panel):
    def __init__(self, parent, suffix, *args, **kwargs):
        super(FileLocationPanel, self).__init__(parent, *args, **kwargs)

        rowSizer = wx.BoxSizer(wx.HORIZONTAL)
        self.filenameSuffix = guiUtils.addLabeledInput(self,
                rowSizer, label = "Filename suffix:",
                defaultValue = suffix,
                size = (160, -1))
        self.filenameSuffix.Bind(wx.EVT_KEY_DOWN, self.generateFilename)
        self.filename = guiUtils.addLabeledInput(self,
                rowSizer, label = "Filename:", size = (200, -1))
        self.generateFilename()
        updateButton = wx.Button(self, -1, 'Update')
        updateButton.SetToolTip(wx.ToolTip(
                "Generate a new filename based on the current time " +
                "and file suffix."))
        updateButton.Bind(wx.EVT_BUTTON, self.generateFilename)
        rowSizer.Add(updateButton)
        self.SetSizerAndFit(rowSizer)

    ## Generate a filename, based on the current time and the
    # user's chosen file suffix.
    def generateFilename(self, event = None):
        # HACK: if the event came from the user typing into the suffix box,
        # then we need to let it go through so that the box gets updated,
        # and we have to wait to generate the new filename until after that
        # point (otherwise we get the old value before) the user hit any keys).
        if event is not None:
            event.Skip()
            wx.CallAfter(self.generateFilename)
        else:
            suffix = self.filenameSuffix.GetValue()
            if suffix:
                suffix = '_' + suffix
            base = time.strftime('%Y%m%d-%H%M%S', time.localtime())
            self.filename.SetValue("%s%s" % (base, suffix))

    ## Set the filename.
    def setFilename(self, newName):
        self.filename.SetValue(newName)

    def GetFilename(self):
        return self.filename.GetValue()

    def GetSuffix(self):
        return self.filenameSuffix.GetValue()


class ExposurePanel(wx.Panel):
    """settings is a dict with the following keys
    `simultaneousExposureTimes` and `shouldExposeSimultaneously` and
    `sequencedExposureSettings`.

    All settings are temporary hack to be backwards compatible with
    old settings mode.  We should probably get rid of this two panels
    and have only exposure settings.
    """
    # We allow either setting per-laser exposure times and activating
    # all cameras as a group, or setting them per-laser and per-camera
    # (and activating each camera-laser grouping in sequence).
    def __init__(self, parent, allLights, allCameras, settings, *args, **kwargs):
        super(ExposurePanel, self).__init__(parent, *args, **kwargs)
        sizer = wx.BoxSizer(wx.VERTICAL)

        ## Controls which set of exposure settings we enable.
        self.simultaneous_checkbox = wx.CheckBox(self, label="Expose cameras simultaneously")
        sizer.Add(self.simultaneous_checkbox, flag=wx.ALL, border=5)

        ## Panel for holding controls for when we expose every camera
        # simultaneously.
        self.simultaneous_panel = SimultaneousExposurePanel(self,
            allLights=allLights,
            exposureTimes=settings['simultaneousExposureTimes'])
        sizer.Add(self.simultaneous_panel, flag=wx.ALL, border=5)

        ## Panel for when we expose each camera in sequence.
        self.sequenced_panel = SequencedExposurePanel(self,
            allLights=allLights,
            allCameras=allCameras,
            exposureTimes=settings['sequencedExposureSettings'])
        sizer.Add(self.sequenced_panel, flag=wx.ALL, border=5)

        # Toggle which panel is displayed based on the checkbox.
        self.simultaneous_checkbox.Bind(wx.EVT_CHECKBOX, self.onExposureCheckbox)
        self.simultaneous_checkbox.SetValue(settings['shouldExposeSimultaneously'])
        self.SetSizerAndFit(sizer)
        self.onExposureCheckbox()

    def ShouldExposeSimultaneously(self):
        return self.simultaneous_checkbox.GetValue()

    def GetSimultaneousExposureTimes(self):
        return self.simultaneous_panel.GetExposureValues()

    def GetSequencedExposureTimes(self):
        return self.sequenced_panel.GetExposureValues()

    def GetExposureSettings(self, cameras):
        if self.ShouldExposeSimultaneously():
            panel = self.simultaneous_panel
        else:
            panel = self.sequenced_panel
        return panel.GetExposureSettings(cameras)

    ## User toggled the exposure controls; show/hide the panels as
    # appropriate.
    def onExposureCheckbox(self, event=None):
        is_simultaneous = self.ShouldExposeSimultaneously()
        # Show the relevant light panel. Disable the unused panel to
        # prevent validation of its controls.
        self.simultaneous_panel.Show(is_simultaneous)
        self.simultaneous_panel.Enable(is_simultaneous)
        self.sequenced_panel.Show(not is_simultaneous)
        self.sequenced_panel.Enable(not is_simultaneous)
        self.GetParent().SetSizerAndFit(self.GetParent().GetSizer())
        ## XXX: not sure if this is needed :/
        self.GetParent().resizeCallback(self.GetParent())

class SimultaneousExposurePanel(wx.Panel):
    def __init__(self, parent, allLights, exposureTimes, *args, **kwargs):
        super(SimultaneousExposurePanel, self).__init__(parent,
                                                        name="simultaneous exposures",
                                                        *args, **kwargs)
        self.allLights = allLights

        sizer = wx.BoxSizer(wx.VERTICAL)

        label = wx.StaticText(self, label="Exposure times for light sources:")
        sizer.Add(label, flag=wx.ALL, border=5)

        ## Ordered list of exposure times for simultaneous exposure mode.
        light_names = [str(l.name) for l in self.allLights]
        self.lightExposureTimes, timeSizer = guiUtils.makeLightsControls(self,
                light_names, exposureTimes)
        sizer.Add(timeSizer)

        useCurrentButton = wx.Button(self, label="Use current settings")
        useCurrentButton.SetToolTip(wx.ToolTip("Use the same settings as are currently used to take images with the '+' button"))
        useCurrentButton.Bind(wx.EVT_BUTTON, self.onUseCurrentExposureSettings)
        sizer.Add(useCurrentButton)

        self.SetSizerAndFit(sizer)

    ## User clicked the "Use current settings" button; fill out the
    # simultaneous-exposure settings text boxes with the current
    # interactive-mode exposure settings.
    def onUseCurrentExposureSettings(self, event=None):
        for i, light in enumerate(self.allLights):
            # Only have an exposure time if the light is enabled.
            val = ''
            if light.getIsEnabled():
                val = str(light.getExposureTime())
            self.lightExposureTimes[i].SetValue(val)

    def GetExposureValues(self):
        return [c.GetValue() for c in self.lightExposureTimes]

    def GetExposureSettings(self, cameras):
        lightTimePairs = []
        for light, exposure in zip(self.allLights, self.GetExposureValues()):
            if light.getIsEnabled() and exposure:
                lightTimePairs.append((light, decimal.Decimal(exposure)))
        settings = [(cameras, lightTimePairs)]
        return settings


class SequencedExposurePanel(wx.Panel):
    def __init__(self, parent, allLights, allCameras, exposureTimes, *args, **kwargs):
        super(SequencedExposurePanel, self).__init__(parent,
                                                     name="sequenced exposures",
                                                     *args, **kwargs)
        self.allLights = allLights
        self.allCameras = allCameras

        ## Maps a camera handler to an ordered list of exposure times.
        self.cameraToExposureTimes = {}

        n_light_sources = len(exposureTimes)
        n_cameras = len(exposureTimes[0])
        sizer = wx.FlexGridSizer(rows=n_light_sources+1, cols=n_cameras+1,
                                 vgap=1, hgap=1)

        for label in [''] + [str(l.name) for l in self.allLights]:
            sizer.Add(wx.StaticText(self, label=label),
                      flag=wx.ALIGN_RIGHT|wx.ALL, border=5)

        for i, camera in enumerate(self.allCameras):
            sizer.Add(wx.StaticText(self, label=str(camera.name)),
                      flag=wx.TOP|wx.ALIGN_RIGHT, border=8)
            times = []
            for (label, defaultVal) in zip([str(l.name) for l in self.allLights],
                                           exposureTimes[i]):
                time_ctrl = wx.TextCtrl(self, size=(40, -1),
                                           name = "exposure: %s for %s" % (label, camera.name))
                time_ctrl.SetValue(defaultVal)
                # allowEmpty=True lets validator know this control may be empty.
                time_ctrl.SetValidator(guiUtils.FLOATVALIDATOR)
                time_ctrl.allowEmpty = True
                sizer.Add(time_ctrl, flag=wx.ALL, border=5)
                times.append(time_ctrl)
            self.cameraToExposureTimes[camera] = times

        self.SetSizerAndFit(sizer)

    def GetExposureValues(self):
        values = []
        for i, camera in enumerate(self.allCameras):
            values.append([c.GetValue() for c in self.cameraToExposureTimes[camera]])
        return values

    def GetExposureSettings(self, cameras):
        exposureSettings = []
        for camera in cameras:
            cameraSettings = self.cameraToExposureTimes[camera]
            settings = []
            for i, light in enumerate(self.allLights):
                if not light.getIsEnabled():
                    continue
                timeControl = cameraSettings[i].GetValue()
                if timeControl:
                    settings.append((light, decimal.Decimal(timeControl)))
            exposureSettings.append(([camera], settings))
        return exposureSettings
