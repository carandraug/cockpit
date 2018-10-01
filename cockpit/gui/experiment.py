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

"""GUI to design and control an experiment.

There's a single :class:`.ExperimentFrame` (window) that provides the
interface to the whole thing.

There's a series of :class:`.ExperimentPanel` s that provides the
interface to different experiment types, e.g., Z stack and 3D SIM.

There's a series of small :class:`wx.Panel` for each configuration
type, e.g.,: location to save files, exposure settings.  These are
used by :class:`ExperimentPanel` s so that different experiment types
can have a common interface to the same settings.

This is still not ideal.  The ideal situation would be that there's no
experiment types, it would all be controls, and the experiment type is
defined by the settings themselves.  For example, it's not 3d unless
the z stack options is selected.  This would minimise code
duplication.  However, cockpit experiments work by subclassing
:class:`cockpit.experiment.experiment.Experiment` and so we match this
logic in the GUI.

"""

import enum
import os.path

import wx

from cockpit.experiment import experimentRegistry
from cockpit.gui import guiUtils


class DataLocationPanel(wx.Panel):
    """Two rows control to select directory and enter a filename template.

    TODO: to make this more reusable, either GetPath() should accept a
    dict of keys to interpret, or the constructor should take a
    function to do the formatting.  Probably the latter.
    """
    def __init__(self, *args, **kwargs):
        super(DataLocationPanel, self).__init__(*args, **kwargs)
        grid = wx.FlexGridSizer(rows=2, cols=2, gap=(5,5))
        grid.AddGrowableCol(1, 1)

        grid.Add(wx.StaticText(self, label="Directory"),
                 flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL)
        ## TODO: read default path from config
        self.dir_ctrl = wx.DirPickerCtrl(self, path=os.getcwd())
        grid.Add(self.dir_ctrl, flag=wx.EXPAND|wx.ALL)

        grid.Add(wx.StaticText(self, label="Filename"),
                 flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL)
        ## TODO: read default template from config
        self.fname_ctrl = wx.TextCtrl(self, value="{time}.mrc")
        grid.Add(self.fname_ctrl, flag=wx.EXPAND|wx.ALL)

        self.SetSizerAndFit(grid)

    def GetPath(self, mapping):
        """Return path for a file after template interpolation.

        Args:
            mapping (dict): maps keys in the template string to their
                substitution value.  Same as :func:`str.format_map`.

        Raises:
            :class:`KeyError` if there are keys in the template
            filename missing from `mapping`.
        """
        dirname = self.dir_ctrl.GetPath()
        template = self.fname_ctrl.GetValue()

        basename = template.format(**mapping)
        return os.path.join(dirname, basename)


class ZStackPanel(wx.Panel):
    class Position(enum.Enum):
        CENTER = 'Current is centre'
        BOTTOM = 'Current is bottom'
        SAVED = 'Use saved top/bottom'

    ## XXX
    position2description = {
        Position.CENTER : 'Current is centre',
        Position.BOTTOM : 'Current is bottom',
        Position.SAVED : 'Use saved top/bottom',
        }

    def __init__(self, parent, settings={}, *args, **kwargs):
        super(ZStackPanel, self).__init__(parent, *args, **kwargs)
        sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.position_choice = wx.Choice(self, choices=[x.value for x in self.Position])
        self.position_choice.SetSelection(Position.CENTER)

        guiUtils.addLabeledInput(self, sizer, label="Z position mode:",
                                 control=self.position_choice)

        self.stackHeight = guiUtils.addLabeledInput(self,
                sizer, label = u"Stack height (\u03bcm):",
                                                    defaultValue = '90')

        self.sliceHeight = guiUtils.addLabeledInput(self,
                sizer, label = u"Slice height (\u03bcm):",
                                                    defaultValue = '100')

        self.SetSizerAndFit(sizer)

    def GetPositionMode(self):
        ## TODO this should return an enum.
        return self.position_choice.GetSelection()

    def GetStackHeight(self):
        return float(self.stackHeight.GetValue())

    def GetSliceHeight(self):
        return float(self.sliceHeight.GetValue())

class ExperimentPanel(wx.Panel):
    """Base class for panels for each experiment type.

    Subclass must have a NAME class property.

    TODO: maybe this should be an abstract class.
    """
    def run_experiment(self):
        pass


class SIM3DExperimentPanel(ExperimentPanel):
    NAME = '3D SIM'
    def __init__(self, *args, **kwargs):
        super(SIM3DExperimentPanel, self).__init__(*args, **kwargs)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.data_panel = DataLocationPanel(self)
        sizer.Add(self.data_panel, flag=wx.EXPAND|wx.ALL)

        self.SetSizerAndFit(sizer)


class ZStackExperimentPanel(ExperimentPanel):
    NAME = 'Z stack'
    def __init__(self, *args, **kwargs):
        super(ZStackExperimentPanel, self).__init__(*args, **kwargs)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.data_panel = ZStackPanel(self)
        sizer.Add(self.data_panel, flag=wx.EXPAND|wx.ALL)

        self.SetSizerAndFit(sizer)

    def run_experiment(self):
        pass


class ExperimentFrame(wx.Frame):
    """Frame (window) to design an experiment.

    This class mainly deals with selecting an experiment type, and the
    loading and saving of experiment settings.  The actual experiment
    design is handled by its central Panel, each experiment type
    having its own.

    """
    def __init__(self, *args, **kwargs):
        super(ExperimentFrame, self).__init__(*args, **kwargs)
        sizer = wx.BoxSizer(wx.VERTICAL)

        border = self.GetFont().GetPointSize() / 2

        settings_sizer = wx.BoxSizer(wx.HORIZONTAL)

        ## TODO: this should be a cockpit configuration (and changed
        ## to fully resolved class names to enable other packages to
        ## provide more experiment types)
        experiments = [
            ZStackExperimentPanel,
            SIM3DExperimentPanel,
        ]

        self.choice = wx.Choice(self, choices=[ex.NAME for ex in experiments])
        self.choice.Bind(wx.EVT_CHOICE, self.onExperimentChoice)
        self.choice.SetSelection(0)
        settings_sizer.Add(self.choice, flag=wx.ALL, border=border)

        for conf in (('Load', self.onLoadButton),
                     ('Save', self.onSaveButton),
                     ('Reset', self.onResetButton)):
            btn = wx.Button(self, label=conf[0])
            btn.Bind(wx.EVT_BUTTON, conf[1])
            settings_sizer.Add(btn, flag=wx.ALL, border=border)

        sizer.Add(settings_sizer)

        self.book =wx.Simplebook(self)
        for ex in experiments:
            ## Each page of the book must have the book as its parent window.
            self.book.AddPage(ex(self.book), text=ex.NAME)

        sizer.Add(self.book, flag=wx.EXPAND, border=border)

        ## TODO: we need to disable the Run button if we are running
        ## an experiment

        ## TODO: the Run button can become an Abort button if an
        ## experiment is running.  If so, we no longer need the Abort
        ## button on the main window.
        self.run_button = wx.Button(self, label='Run')
        self.run_button.SetBackgroundColour(wx.GREEN)
        self.run_button.Bind(wx.EVT_BUTTON, self.onRunButton)
        ## ?? Maybe have it as bar across the whole Frame
        sizer.AddStretchSpacer()
        sizer.Add(self.run_button, flag=wx.ALL|wx.EXPAND, border=border)

        self.SetSizerAndFit(sizer)

    def onExperimentChoice(self, event):
        print (event.GetSelection())
        self.book.ChangeSelection(event.GetSelection())
        # if selection == wx.NOT_FOUND:
        #     return

        # try:
        #     selected_panel = self.experiment_panels[selection]
        # except IndexError as e:
        #     ## Not sure how this can happen, but let's do nothing then
        #     return

        # if self.GetSizer().Replace(self.current_panel, selected_panel):
        #     self.current_panel.Hide()
        #     self.current_panel = selected_panel
        #     self.current_panel.Show()
        #     self.Layout()
        #     self.Fit()

    def onRunButton(self, event):
        pass

    def applySettings(self, settings):
        pass

    def onLoadButton(self, event):
        dialog = wx.FileDialog(self, message='Select file to load settings',
                               style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST)
        if dialog.ShowModal() == wx.ID_CANCEL:
            return

        filepath = dialog.GetPath()
        print(filepath)
        settings = filepath # TODO read file for settings in whatever format
        self.applySettings(settings)

    def onSaveButton(self, event):
        dialog = wx.FileDialog(self, message='Select file to save settings',
                               style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT)
        if dialog.ShowModal() == wx.ID_CANCEL:
            return

        filepath = dialog.GetPath()
        print(filepath)
        ## TODO convert settings to write


    def onResetButton(self, event):
        ## XXX: I'm not sure this is needed.  Reset to what really? We
        ## have the option to load from a settings file already.
        pass
