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

TODO: disable z stack if there's no z stage
TODO: disable multiposition if there's no xy stage
TODO: should location of saved data part of the experiment settings?
"""

import enum
import os.path
import sys

import wx

import cockpit.events
import cockpit.experiment


class StaticTextLine(wx.Control):
    """A Static Line with a title to split panels in a vertical orientation.

    In the ideal case, we would StaticBoxes for this but that looks
    pretty awful and broken unless used with StaticBoxSizer
    https://trac.wxwidgets.org/ticket/18253
    """
    def __init__(self, parent, id=wx.ID_ANY, label="",
                 style=wx.BORDER_NONE, *args, **kwargs):
        super(StaticTextLine, self).__init__(parent=parent, id=id, style=style,
                                             *args, **kwargs)
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        border = self.GetFont().GetPointSize()
        sizer.Add(wx.StaticText(self, label=label), proportion=0,
                  flag=wx.RIGHT, border=border)
        sizer.Add(wx.StaticLine(self), proportion=1,
                  flag=wx.ALIGN_CENTER_VERTICAL, border=border)
        self.SetSizerAndFit(sizer)


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

    def GetNumTimePoints(self):
        return int(self.number_points.GetValue())
    def GetTimeInterval(self):
        return float(self.interval.GetValue())


class ExposureSettingsPanel(wx.Panel):
    def __init__(self, *args, **kwargs):
        super(ExposureSettingsPanel, self).__init__(*args, **kwargs)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.reload_button = wx.Button(self, label='Reload imaging settings')
        self.reload_button.Bind(wx.EVT_BUTTON, self.OnReloadSettings)
        sizer.Add(self.reload_button)

        self.simultaneous_checkbox = wx.CheckBox(self,
                                                 label='Simultaneous imaging')
        self.simultaneous_checkbox.Bind(wx.EVT_CHECKBOX,
                                        self.OnSimultaneousImaging)
        sizer.Add(self.simultaneous_checkbox)

        ## TODO: read this from configuration
        cameras = ['west', 'east']
        lights = ['ambient', '405', '488', '572', '604']
        # grid = wx.FlexGridSizer(rows=len(cameras)+1, cols=len(lights)+1,
        #                         vgap=1, hgap=1)
        # grid.Add((0,0))
        # for l in lights:
        #     grid.Add(wx.StaticText(self, label=l))
        # for c in cameras:
        #     grid.Add(wx.StaticText(self, label=c))
        #     for l in lights:
        #         grid.Add(wx.TextCtrl(self, value='0.0'))
        # sizer.Add(grid)

        self.SetSizerAndFit(sizer)

    def OnReloadSettings(self, event):
        pass

    def OnSimultaneousImaging(self, event):
        pass


class SIMSettingsPanel(wx.Panel):
    def __init__(self, *args, **kwargs):
        super(SIMSettingsPanel, self).__init__(*args, **kwargs)
        from cockpit.experiment.structuredIllumination import COLLECTION_ORDERS
        self._order = wx.Choice(self, choices=list(COLLECTION_ORDERS.keys()))
        self._order.SetSelection(0)
        self._angles = wx.SpinCtrl(self, min=1, max=(2**31)-1, initial=3)
        lights = ['ambient', '405', '488', '572', '604']

        border = self.GetFont().GetPointSize() /2
        sizer = wx.BoxSizer(wx.VERTICAL)

        row1_sizer = wx.BoxSizer(wx.HORIZONTAL)
        for conf in (('Collection order', self._order),
                     ('Number of angles', self._angles)):
            row1_sizer.Add(wx.StaticText(self, label=conf[0]),
                           flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL, border=border)
            row1_sizer.Add(conf[1], flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL,
                           border=border)
        sizer.Add(row1_sizer)

        grid = wx.FlexGridSizer(rows=2, cols=len(lights)+1, gap=(1,1))
        grid.Add((0,0))
        for l in lights:
            grid.Add(wx.StaticText(self, label=l),
                     flag=wx.ALIGN_CENTER_HORIZONTAL)
        grid.Add(wx.StaticText(self, label='Bleach compensation (%)'),
                 flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL, border=border)
        for l in lights:
            grid.Add(wx.TextCtrl(self, value='0.0'))
        sizer.Add(grid)

        self.SetSizer(sizer)

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


class StatusPanel(wx.Panel):
    """A panel with progress text and progress bar.

    Still not sure about the free text.  May be more useful to have
    multiple sections, such as estimated end time and estimated time
    left.

    """
    def __init__(self, *args, **kwargs):
        super(StatusPanel, self).__init__(*args, **kwargs)
        sizer = wx.BoxSizer(wx.VERTICAL)

        ## XXX: not sure about the status text.  We also have the
        ## space below the progress bar, left of the run and stop
        ## buttons.  But I feel like this should be seen as one panel
        ## with the progress bar.
        self.text = wx.StaticText(self, style=wx.ALIGN_CENTRE_HORIZONTAL,
                                  label='This is progress...')
        sizer.Add(self.text, flag=wx.ALL^wx.BOTTOM|wx.EXPAND|wx.ALIGN_CENTER)

        self.progress = wx.Gauge(self)
        sizer.Add(self.progress, flag=wx.ALL^wx.TOP|wx.EXPAND|wx.ALIGN_CENTER)

        self.SetSizerAndFit(sizer)

    def SetText(self, text):
        self.text.SetLabelText(text)
        self.Layout()


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
        border = self.GetFont().GetPointSize() / 2

        self.z_control = CheckStaticBox(self, label="Z Stack")
        sizer.Add(self.z_control, flag=wx.EXPAND|wx.ALL, border=border)
        self.z_panel = ZSettingsPanel(self)
        self.z_control.addControlled(self.z_panel)
        sizer.Add(self.z_panel, border=border)

        self.time_control = CheckStaticBox(self, label="Time Series")
        sizer.Add(self.time_control, flag=wx.EXPAND|wx.ALL, border=border)
        self.time_panel = TimeSettingsPanel(self)
        self.time_control.addControlled(self.time_panel)
        sizer.Add(self.time_panel, border=border)

        self.points_control = CheckStaticBox(self, label="Multi Position")
        sizer.Add(self.points_control, flag=wx.EXPAND|wx.ALL, border=border)

        sizer.Add(StaticTextLine(self, label="Exposure settings"),
                  flag=wx.ALL|wx.EXPAND, border=border)
        self.exposure_panel = ExposureSettingsPanel(self)
        sizer.Add(self.exposure_panel, flag=wx.EXPAND|wx.ALL, border=border)


        self.SetSizerAndFit(sizer)

    def PrepareExperiment(self):
        """Prepare a :class:`cockpit.experiment.experiment.Experiment` to run.

        Raises:
            :class:`RuntimeError` in case of failing

        TODO: I'm not a big fan of this raising exceptions for some of
        this not really exceptions such as existing files.  Maybe
        return None?
        """
        numReps = 1
        repDuration = 0.0
        if self.time_control.IsEnabled():
            numReps = self.time_control.GetNumTimePoints()
            repDuration = self.time_control.GetTimeInterval()

        zPositioner = None
        altBottom = None
        zHeight = None
        sliceHeight = None
        if self.z_panel.IsEnabled():
            zPositioner = None
            altBottom = None
            zHeight = None
            sliceHeight = None

        cameras = []
        lights = []
        exposureSettings = [([], [()])]

        otherHandlers = []
        metadata = ''
        save_path = '/usr/lib'
        if os.path.lexists(save_path):
            if os.path.isdir(save_path):
                caption = ("A directory named '%s' already exists."
                           % os.path.basename(save_path))
                message = ("A directory already exists in '%s'."
                           " It can't be replaced."
                           % os.path.dirname(save_path))
                wx.MessageBox(message=message, caption=caption,
                              style=wx.OK|wx.ICON_ERROR, parent=self)
                raise RuntimeError("selected filepath '%s' is a directory"
                                   % save_path)

            ## Same dialog text that a wx.FileDialog displays with
            ## wx.FD_OVERWRITE_PROMPT.  We change the default to
            ## 'no' and make it a warning/exclamation.
            caption = ("A file named '%s' already exists."
                       " Do you want to replace it?"
                       % os.path.basename(save_path))
            message = ("The file already exists in '%s'."
                       " Replacing it will overwrite its contents"
                       % os.path.dirname(save_path))
            dialog = wx.MessageDialog(self, message=message, caption=caption,
                                      style=(wx.YES_NO|wx.NO_DEFAULT
                                             |wx.ICON_EXCLAMATION))
            ## We use yes/no instead of yes/cancel because
            ## CANCEL_DEFAULT has no effect on MacOS
            dialog.SetYesNoLabels('Replace', 'Cancel')
            if dialog.ShowModal() != wx.ID_YES:
                raise RuntimeError("selected filepath '%s' already exists"
                                   % save_path)

        experiment = True
        return experiment

class SIMExperimentPanel(ExperimentPanel):
    NAME = 'Structured Illumination'

    def __init__(self, *args, **kwargs):
        super(SIMExperimentPanel, self).__init__(*args, **kwargs)
        self._sim_control = SIMSettingsPanel(self)

        sizer = self.GetSizer()
        sizer.Add(StaticTextLine(self, label="SIM settings"),
                  flag=wx.EXPAND|wx.ALL, border=5)
        sizer.Add(self._sim_control, flag=wx.EXPAND|wx.ALL)


class ExperimentFrame(wx.Frame):
    """Frame (window) to design an experiment.

    This class mainly deals with selecting an experiment type, and the
    loading and saving of experiment settings.  The actual experiment
    design is handled by its central Panel, each experiment type
    having its own.

    """
    def __init__(self, *args, **kwargs):
        super(ExperimentFrame, self).__init__(*args, **kwargs)
        self.experiment = None

        ## TODO: This is a menu bar so that open will open a new
        ## experiment tab or frame (to be implemented)
        menu_bar = wx.MenuBar()
        file_menu = wx.Menu()
        ## TODO: Reset settings ???
        for conf in ((wx.ID_OPEN, self.OnOpen),
                     (wx.ID_SAVEAS, self.OnSaveAs),
                     (wx.ID_CLOSE, self.OnClose)):
            file_menu.Append(conf[0])
            self.Bind(wx.EVT_MENU, conf[1], id=conf[0])
        menu_bar.Append(file_menu, '&File')
        self.SetMenuBar(menu_bar)

        ## TODO: this should be a cockpit configuration (and changed
        ## to fully resolved class names to enable other packages to
        ## provide more experiment types).  Maybe we should have a
        ## AddExperiment method which we then reparent to the book?
        ## XXX: I really wouldn't like the passing of classes when
        ## they're only to be instatiated once anyway.
        experiments = [
            ExperimentPanel,
            SIMExperimentPanel,
        ]

        self._book =wx.Choicebook(self)
        for ex in experiments:
            self._book.AddPage(ex(self._book), text=ex.NAME)

        ## XXX: I'm unsure about DataLocation being part of the
        ## ExperimentFrame instead of the many pages in the book.
        ## Some experiments may have special data location
        ## requirements (save in directory for example) and this takes
        ## away that flexibility.  However, it feels to be a bit
        ## special and something to share between panels.
        self._data_location = DataLocationPanel(self)

        self._status = StatusPanel(self)

        ## The run button is not a toggle button because we can't
        ## really pause the experiment.  We can only abort it and
        ## starting it starts a new experiment, not continue from
        ## where we paused.
        self._run = wx.Button(self, label='Run')
        self._run.Bind(wx.EVT_BUTTON, self.OnRunButton)
        self._abort = wx.Button(self, label='Abort')
        self._abort.Bind(wx.EVT_BUTTON, self.OnAbortButton)

        ## We don't subscribe to USER_ABORT because that means user
        ## wants to abort, not that the experiment has been aborted.
        ## If an experiment is aborted, it still needs to go through
        ## cleanup and then emits EXPERIMENT_COMPLETE as usual.
        cockpit.events.subscribe(cockpit.events.EXPERIMENT_COMPLETE,
                                 self.OnExperimentEnd)

        sizer = wx.BoxSizer(wx.VERTICAL)
        border = self.GetFont().GetPointSize() / 2
        sizer.Add(self._book, flag=wx.EXPAND|wx.ALL, border=border)
        sizer.AddStretchSpacer()
        for panel in (StaticTextLine(self, label="Data Location"),
                      self._data_location, self._status):
            sizer.Add(panel, flag=wx.ALL|wx.EXPAND, border=border)

        buttons_sizer = wx.BoxSizer(wx.HORIZONTAL)
        for button in (self._run, self._abort):
            buttons_sizer.Add(button, flag=wx.ALL, border=border)
        sizer.Add(buttons_sizer, flag=wx.ALL|wx.ALIGN_RIGHT, border=border)

        self.SetSizerAndFit(sizer)

    def OnRunButton(self, event):
        self._run.Disable()
        self._book.Disable()
        self._status.SetText('Preparing experiment')

        ## XXX: I'm not sure about this try/catch, returning None
        ## seems nicer.  However, we would still need to catch an
        ## exception, this is one of those important places to catch
        ## them.
        try:
            ## TODO: how long does this takes?  Is it bad we are blocking?
            self.experiment = self._book.GetCurrentPage().PrepareExperiment()
        except Exception as e:
            self._status.SetText('Failed to start experiment:\n%s' % e)
            self.OnExperimentEnd()
            return

        self._status.SetText('Experiment starting')
        wx.CallAfter(self.experiment.run)

    def OnAbortButton(self, event):
        if self.experiment is None or not self.experiment.is_running():
            return

        caption = "Aborting experiment."
        message = "Should the acquired data be discarded?"
        ## TODO: actually implement the discard of data.
        dialog = wx.MessageDialog(self, message=message, caption=caption,
                                  style=(wx.YES_NO|wx.CANCEL|wx.NO_DEFAULT
                                         |wx.ICON_EXCLAMATION))
        dialog.SetYesNoLabels('Discard', 'Keep')
        status = dialog.ShowModal()
        if status == wx.CANCEL:
            return
        elif status == wx.YES: # discard data
            raise NotImplementedError("don't know how to discard data")

        self._status.SetText('Aborting experiment')
        cockpit.events.publish(cockpit.events.USER_ABORT)

    def OnExperimentEnd(self): # for cockpit.events, not wx.Event
        self._run.Enable()
        self._book.Enable()

    def OnOpen(self, event):
        dialog = wx.FileDialog(self, message='Select experiment to open',
                               style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST)
        if dialog.ShowModal() != wx.ID_OK:
            return
        filepath = dialog.GetPath()
        print(filepath)

    def OnSaveAs(self, event):
        dialog = wx.FileDialog(self, message='Select file to save experiment',
                               style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT)
        if dialog.ShowModal() != wx.ID_OK:
            return
        filepath = dialog.GetPath()
        print(filepath)

    def OnClose(self, event):
        if self.experiment is not None and self.experiment.is_running():
            ## Only inform that experiment is running.  Do not give an
            ## option to abort experiment to avoid accidents.
            caption = "Experiment is running."
            message = ("This experiment is still running."
                       " Abort the experiment first.")
            wx.MessageBox(message=message, caption=caption, parent=self,
                          style=wx.OK|wx.CENTRE|wx.ICON_ERROR)
        else:
            self.Close()

if __name__ == "__main__":
    app = wx.App()
    frame = ExperimentFrame(None)

    import wx.lib.inspection
    wx.lib.inspection.InspectionTool().Show()

    frame.Show()
    app.MainLoop()
