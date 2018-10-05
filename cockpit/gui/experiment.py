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

# from cockpit.experiment import experimentRegistry
# from cockpit.gui import guiUtils


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
    """Not a big fan of slice hight set to zero to have a 2d experiment.
    That should be minimum slice height.  To disable Zstack, just
    don't select a 3d experiment.

    """
    class Position(enum.Enum):
        CENTER = 'Current Z is centre'
        BOTTOM = 'Current Z is bottom'
        SAVED = 'Use saved Z top/bottom'

    ## XXX
    position2description = {
        Position.CENTER : 'Current is Z centre',
        Position.BOTTOM : 'Current is Z bottom',
        Position.SAVED : 'Use saved Z top/bottom',
        }

    def __init__(self, parent, settings={}, *args, **kwargs):
        super(ZStackPanel, self).__init__(parent, *args, **kwargs)
        sizer = wx.BoxSizer(wx.HORIZONTAL)

        self.position = wx.Choice(self, choices=[x.value for x in self.Position])
        self.position.Bind(wx.EVT_CHOICE, self.onPositionChoice)
        self.position.SetSelection(0)
        sizer.Add(self.position)

        ## TODO: this should some config (maybe last used)
        default_stack_height = '90'
        default_slice_height = '100'

        sizer.Add(wx.StaticText(self, label="Stack height (µm)"))
        self.stack_height = wx.TextCtrl(self, value=default_stack_height)
        sizer.Add(self.stack_height)

        sizer.Add(wx.StaticText(self, label="Slice height (µm)"))
        self.slice_height = wx.TextCtrl(self, value=default_slice_height)
        sizer.Add(self.slice_height)

        self.SetSizerAndFit(sizer)

    def onPositionChoice(self, event):
        selection = event.GetSelection()
        ## XXX We shouldn't have to do this list nidexing...
        if [x for x in self.Position][selection] == ZStackPanel.Position.SAVED:
            self.stack_height.Disable()
        else:
            self.stack_height.Enable()

    def GetStackHeight(self):
        if [x for x in self.Position][selection] == ZStackPanel.Position.SAVED:
            pass
        else:
            ## TODO: If slice height is zero, this is not really a 3d
            ## experiment.  Not sure why this special case, I guess the
            ## Experiment class breaks.
            slice_height = float(self.slice_height.GetValue())
            if slice_height == 0:
                ## FIXME Not sure why, but this was here before, and I
                ## don't want to break an experiment just yet.  The
                ## experiment class should handle fine if height is zero.
                stack_height = 1e-6
            else:
                stack_height = float(self.stack_height.GetValue())
        return stack_height

    def GetSliceHeight(self):
        slice_height = float(self.slice_height.GetValue())
        if slice_height == 0:
            ## FIXME Not sure why, but this was here before, and I
            ## don't want to break an experiment just yet.  The
            ## experiment class should handle fine if height is zero.
            slice_height = 1e-6
        return slice_height


class ExposureSettings(wx.Panel):
    pass


class CheckStaticBox(wx.Control):
    """A StaticBox whose title is a checkbox to disable its content.

    This does not exist in wxWidgets and the title needs to be a
    string.  Because this is to be stacked on a vertical box sizer, we
    fake it with an horizontal line.
    """
    def __init__(self, *args, **kwargs):
        super(CheckStaticBox, self).__init__(*args, **kwargs)

## TODO: we should have an interface class so that we can have
## experiments not subclassing with our ExperimentPanel at all.

class ExperimentPanel(wx.Panel):
    NAME = 'Widefield'
    def __init__(self, *args, **kwargs):
        super(ExperimentPanel, self).__init__(*args, **kwargs)
        sizer = wx.BoxSizer(wx.VERTICAL)

        split = wx.BoxSizer(wx.HORIZONTAL)
        # split.Add(wx.CheckBox(self, label="foo"))
        # split.Add(wx.StaticLine(self, size=(80,10)), flag=wx.EXPAND|wx.ALL, border=10)

        line = wx.StaticLine(self)
        split.Add(line, flag=wx.EXPAND|wx.ALL, border=10)
        sizer.Add(split, flag=wx.EXPAND|wx.ALL)
        self.data_panel = DataLocationPanel(self)
        sizer.Add(self.data_panel, flag=wx.EXPAND|wx.ALL)
        self.SetSizer(sizer)

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
        for conf in ((wx.ID_OPEN, self.onOpen), (wx.ID_SAVEAS, self.onSaveAs)):
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


app = wx.App()
frame = ExperimentFrame(None)

import wx.lib.inspection
wx.lib.inspection.InspectionTool().Show()

frame.Show()
app.MainLoop()
