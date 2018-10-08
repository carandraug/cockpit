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
import sys

import wx

# from cockpit.experiment import experimentRegistry
# from cockpit.gui import guiUtils


class ZSettingsPanel(wx.Panel):
    """
    TODO: ability to select number of z panels instead of µm height
    TODO: pick ideal slice height for microscope configuration
    TODO: there were workarounds for 2D that set values to 1e-6 if height was 0
    TODO: z slice set to zero should be minimum step of z stage
    TODO: read saved z settings from cockpit
    """
    class Position(enum.IntEnum):
        ## I don't feel right about starting this enum at zero but I
        ## want to use them as indices in the choices menu.  hmmmm...
        CENTER = 0
        BOTTOM = 1
        SAVED = 2

    position2description = {
        Position.CENTER : 'Current is centre',
        Position.BOTTOM : 'Current is bottom',
        Position.SAVED : 'Saved top/bottom',
    }

    def __init__(self, parent, settings={}, *args, **kwargs):
        super(ZSettingsPanel, self).__init__(parent, *args, **kwargs)
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        border = self.GetFont().GetPointSize() /2

        descriptions = [self.position2description[x] for x in self.Position]
        self.position = wx.Choice(self, choices=descriptions)
        self.position.Bind(wx.EVT_CHOICE, self.OnPositionChoice)
        self.position.SetSelection(0)
        sizer.Add(self.position, flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL,
                  border=border)

        ## TODO: this should some config (maybe last used)
        default_stack_height = '90'
        default_slice_height = '100'

        self.stack_height = wx.TextCtrl(self, value=default_stack_height)
        self.slice_height = wx.TextCtrl(self, value=default_slice_height)
        self.number_slices = wx.SpinCtrl(self, min=1, max=(2**31)-1, initial=1)

        for conf in (('Stack height (µm)', self.stack_height),
                     ('Slice height (µm)', self.slice_height),
                     ('Number slices', self.number_slices)):
            sizer.Add(wx.StaticText(self, label=conf[0]),
                      flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL, border=border)
            sizer.Add(conf[1], flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL,
                      border=border)

        self.SetSizerAndFit(sizer)

    def _use_saved_z(self):
        return (self.Position(self.position.GetSelection())
                == self.Position.SAVED)

    def OnPositionChoice(self, event):
        self.stack_height.Enable(not self._use_saved_z())

    def GetStackHeight(self):
        if self._use_saved_z():
            raise NotImplementedError()
        else:
            return float(self.stack_height.GetValue())

    def GetSliceHeight(self):
        ## TODO: if slice height is zero, pick the smallest z step
        ## (same logic what we do with time).  But shold we do this
        ## here or should we do it in experiment?
        return float(self.slice_height.GetValue())


class TimeSettingsPanel(wx.Panel):
    def __init__(self, *args, **kwargs):
        super(TimeSettingsPanel, self).__init__(*args, **kwargs)
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        border = self.GetFont().GetPointSize() /2

        self.number_points = wx.SpinCtrl(self, min=1, max=(2**31)-1, initial=1)
        self.interval = wx.TextCtrl(self, value='0')

        for conf in (('Number timepoints', self.number_points),
                     ('Time interval (s)', self.interval)):
            sizer.Add(wx.StaticText(self, label=conf[0]),
                      flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL, border=border)
            sizer.Add(conf[1], flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL,
                      border=border)

        self.SetSizerAndFit(sizer)

class ExposureSettings(wx.Panel):
    pass

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



class CheckStaticBox(wx.Control):
    """A StaticBox whose title is a checkbox to disable its content.

    This does not exist in wxWidgets and the title needs to be a
    string.  Because this is to be stacked on a vertical box sizer, we
    fake it with an horizontal line.

    TODO: This should have and interface that is much closer to
    wx.StaticBox class but I can't figure out how to make those look
    right.  If this was done that way, the checkbox would
    enable/disable its children instead of keeping our own list of
    controlled panels.

    TODO: maybe we could implement this widget upstream?
    """
    def __init__(self, parent, id=wx.ID_ANY, label="", *args, **kwargs):
        super(CheckStaticBox, self).__init__(parent, style=wx.BORDER_NONE,
                                             *args, **kwargs)
        self._controlled = []

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.checkbox = wx.CheckBox(self, label=label)
        self.checkbox.Bind(wx.EVT_CHECKBOX, self.onCheckBox)
        sizer.Add(self.checkbox)
        sizer.Add(wx.StaticLine(self), proportion=1,
                  flag=wx.ALIGN_CENTER_VERTICAL)
        self.SetSizerAndFit(sizer)

    def addControlled(self, panel):
        panel.Enable(self.checkbox.IsChecked())
        self._controlled.append(panel)

    def onCheckBox(self, event):
        is_checked = event.IsChecked()
        for panel in self._controlled:
            panel.Enable(is_checked)

## TODO: we should have an interface class so that we can have
## experiments not subclassing with our ExperimentPanel at all.

class ExperimentPanel(wx.Panel):
    NAME = 'Widefield'
    def __init__(self, *args, **kwargs):
        super(ExperimentPanel, self).__init__(*args, **kwargs)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.z_control = CheckStaticBox(self, label="Z Stack")
        sizer.Add(self.z_control, flag=wx.EXPAND|wx.ALL)
        self.z_panel = ZSettingsPanel(self)
        self.z_control.addControlled(self.z_panel)
        sizer.Add(self.z_panel)

        self.time_control = CheckStaticBox(self, label="Time Series")
        sizer.Add(self.time_control, flag=wx.EXPAND|wx.ALL)
        self.time_panel = TimeSettingsPanel(self)
        self.time_control.addControlled(self.time_panel)
        sizer.Add(self.time_panel)

        self.points_control = CheckStaticBox(self, label="Multi Position")
        sizer.Add(self.points_control, flag=wx.EXPAND|wx.ALL)
        # self.z_panel = ZStackPanel(self)
        # self.z_control.addControlled(self.z_panel)
        # sizer.Add(self.z_panel)

        self.exposure_panel = ExposureSettings(self)
        sizer.Add(self.exposure_panel)

        self.data_panel = DataLocationPanel(self)
        sizer.Add(self.data_panel, 1, flag=wx.EXPAND|wx.ALL)

        self.SetSizerAndFit(sizer)

    def run_experiment(self):
        pass


class SIM3DExperimentPanel(ExperimentPanel):
    NAME = '3D SIM'
    pass
    # def __init__(self, *args, **kwargs):
    #     super(SIM3DExperimentPanel, self).__init__(*args, **kwargs)
    #     sizer = wx.BoxSizer(wx.VERTICAL)


    #     self.SetSizerAndFit(sizer)


class ZStackExperimentPanel(ExperimentPanel):
    NAME = 'Z stack'
    # def __init__(self, *args, **kwargs):
    #     super(ZStackExperimentPanel, self).__init__(*args, **kwargs)
    #     sizer = wx.BoxSizer(wx.VERTICAL)

    #     self.data_panel = ZStackPanel(self)
    #     sizer.Add(self.data_panel, flag=wx.EXPAND|wx.ALL)

    #     self.SetSizerAndFit(sizer)

    # def run_experiment(self):
    #     pass


class ExperimentFrame(wx.Frame):
    """Frame (window) to design an experiment.

    This class mainly deals with selecting an experiment type, and the
    loading and saving of experiment settings.  The actual experiment
    design is handled by its central Panel, each experiment type
    having its own.

    """
    def __init__(self, *args, **kwargs):
        super(ExperimentFrame, self).__init__(*args, **kwargs)

        ## This is a menu bar so that open will open a new experiment
        ## tab (to be implemented)
        menu_bar = wx.MenuBar()
        file_menu = wx.Menu()
        ## TODO: Reset settings ???
        for conf in ((wx.ID_OPEN, self.onOpen),
                     (wx.ID_SAVEAS, self.onSaveAs),
                     (wx.ID_CLOSE, self.onClose)):
            file_menu.Append(conf[0])
            self.Bind(wx.EVT_MENU, conf[1], id=conf[0])
        menu_bar.Append(file_menu, '&File')
        self.SetMenuBar(menu_bar)

        sizer = wx.BoxSizer(wx.VERTICAL)
        border = self.GetFont().GetPointSize() / 2

        ## TODO: this should be a cockpit configuration (and changed
        ## to fully resolved class names to enable other packages to
        ## provide more experiment types)
        experiments = [
            ExperimentPanel,
            ZStackExperimentPanel,
            SIM3DExperimentPanel,
        ]

        self.book =wx.Choicebook(self)
        for ex in experiments:
            self.book.AddPage(ex(self.book), text=ex.NAME)
        sizer.Add(self.book, flag=wx.EXPAND|wx.ALL, border=border)

        ## TODO: we need to disable the Run button if we are running
        ## an experiment
        ## TODO: the Run button can become an Abort button if an
        ## experiment is running.  If so, we no longer need the Abort
        ## button on the main window.
        self.run_button = wx.Button(self, label='Run')
        self.run_button.SetBackgroundColour(wx.GREEN)
        self.run_button.Bind(wx.EVT_BUTTON, self.onRun)
        ## ?? Maybe have it as bar across the whole Frame
        sizer.AddStretchSpacer()
        sizer.Add(self.run_button, flag=wx.ALL|wx.EXPAND, border=border)

        self.SetSizerAndFit(sizer)

    def onRun(self, event):
        pass

    def onAbort(self, event):
        pass

    def onOpen(self, event):
        dialog = wx.FileDialog(self, message='Select experiment to open',
                               style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST)
        if dialog.ShowModal() == wx.ID_CANCEL:
            return
        filepath = dialog.GetPath()
        print(filepath)

    def onSaveAs(self, event):
        dialog = wx.FileDialog(self, message='Select file to save experiment',
                               style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT)
        if dialog.ShowModal() == wx.ID_CANCEL:
            return
        filepath = dialog.GetPath()
        print(filepath)

    def onClose(self, event):
        ## TODO: ask if they're sure and want to save settings?
        self.Close()

app = wx.App()
frame = ExperimentFrame(None)

# import wx.lib.inspection
# wx.lib.inspection.InspectionTool().Show()

frame.Show()
app.MainLoop()
