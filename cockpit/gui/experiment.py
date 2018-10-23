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
import time

import wx

import cockpit.events
import cockpit.experiment


class ExperimentFrame(wx.Frame):
    """Frame (window) to run an experiment.

    This class only deals with selecting an experiment type, the
    loading and saving of experiment settings, and the start of
    experiment.  The actual experiment design is handled by its
    central Panel, each experiment type having its own.  The Run
    button simply interacts with the experiment Panel.

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
            WidefieldExperimentPanel,
            SIMExperimentPanel,
            RotatorSweepExperimentPanel,
        ]

        self._book =wx.Choicebook(self)
        for ex in experiments:
            self._book.AddPage(ex(self._book), text=ex.NAME)

        ## XXX: I'm unsure about DataLocation being part of the
        ## ExperimentFrame instead of each experiment panel in the
        ## book.  Some experiments may have special data location
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

        self.Bind(wx.EVT_CLOSE, self.OnClose)

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
        self.OnExperimentStart()
        self._status.SetText('Preparing experiment')

        ## TODO: rethink this error handling
        def cancel_preparation(msg):
            self._status.SetText('Failed to start experiment:\n' + msg)
            self.OnExperimentEnd()

        try:
            fpath = self.GetSavePath()
        except Exception as e:
            cancel_preparation(str(e))
            return

        if not self.CheckFileOverwrite(fpath):
            cancel_preparation('user cancelled to not overwrite file')
            return

        experiment_panel = self._book.GetCurrentPage()
        try:
            ## TODO: how long does this takes?  Is it bad we are blocking?
            self.experiment = experiment_panel.PrepareExperiment(fpath)
        except Exception as e:
            cancel_preparation(str(e))
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
            raise NotImplementedError("don't know how to discard data yet")

        self._status.SetText('Aborting experiment')
        cockpit.events.publish(cockpit.events.USER_ABORT)

    def OnExperimentStart(self):
        self._run.Disable()
        self._book.Disable()

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
        if (event.CanVeto() and self.experiment is not None
            and self.experiment.is_running()):
            ## Only inform that experiment is running.  Do not give an
            ## option to abort experiment to avoid accidents.
            caption = "Experiment is running."
            message = ("This experiment is still running."
                       " Abort the experiment first.")
            msg = wx.MessageBox(message=message, caption=caption, parent=None,
                          style=wx.OK|wx.CENTRE|wx.ICON_ERROR)
            event.Veto()
        else:
            self.Destroy()

    def GetSavePath(self):
        ## TODO: format of time should be a configuration
        mapping = {
            'time' : time.strftime('%Y%m%d-%H%M%S', time.localtime())
        }
        ## TODO: get more mapping from the current experiment panel.
        try:
            fpath = self._data_location.GetPath(mapping)
        except KeyError as e:
            raise RuntimeError("missing path substitution value for %s" % e)
        return fpath

    def CheckFileOverwrite(self, fpath):
        """
        Returns:
            `True` if we can continue (either file does not exist or
            user is ok with overwriting it).  `False` otherwise (file
            is a directory or user does not want to overwrite).
        """
        if os.path.isdir(fpath):
            caption = ("A directory named '%s' already exists."
                       % os.path.basename(fpath))
            message = ("A directory already exists in '%s'."
                       " It can't be replaced."
                       % os.path.dirname(fpath))
            wx.MessageBox(message=message, caption=caption,
                          style=wx.OK|wx.ICON_ERROR, parent=self)
            self._status.SetText("selected filepath '%s' is a directory"
                                 % fpath)
            return False

        if os.path.lexists(fpath):
            ## Same dialog text that a wx.FileDialog displays with
            ## wx.FD_OVERWRITE_PROMPT.  We change the default to
            ## 'no' and make it a warning/exclamation.
            caption = ("A file named '%s' already exists."
                       " Do you want to replace it?"
                       % os.path.basename(fpath))
            message = ("The file already exists in '%s'."
                       " Replacing it will overwrite its contents"
                       % os.path.dirname(fpath))
            dialog = wx.MessageDialog(self, message=message, caption=caption,
                                      style=(wx.YES_NO|wx.NO_DEFAULT
                                             |wx.ICON_EXCLAMATION))
            ## We use yes/no instead of yes/cancel because
            ## CANCEL_DEFAULT has no effect on MacOS
            dialog.SetYesNoLabels('Replace', 'Cancel')
            if dialog.ShowModal() != wx.ID_YES:
                self._status.SetText("selected filepath '%s' already exists"
                                     % fpath)
                return False

        return True

class AbstractExperimentPanel(wx.Panel):
    """Parent class for the panels to design an experiment.

    TODO: we should have an interface class so that we can have
    experiments not subclassing with our ExperimentPanel at all.
    """
    def PrepareExperiment(self):
        """Prepare a :class:`cockpit.experiment.experiment.Experiment` to run.

        Raises:
            :class:`RuntimeError` in case of failing

        TODO: I'm not a big fan of this raising exceptions for some of
        this not really exceptions such as existing files.  Maybe
        return None?
        """
        raise NotImplementedError('concrete class must implement this')


class WidefieldExperimentPanel(AbstractExperimentPanel):
    NAME = 'Widefield'
    def __init__(self, *args, **kwargs):
        super(WidefieldExperimentPanel, self).__init__(*args, **kwargs)

        self._z_stack = ZSettingsPanel(self)
        self._time = TimeSettingsPanel(self)
        self._positions = PositionSettingsPanel(self)
        self._exposure = ExposureSettingsPanel(self)

        sizer = wx.BoxSizer(wx.VERTICAL)
        border = self.GetFont().GetPointSize() / 2
        for conf in (('Z Stack', self._z_stack),
                     ('Time Series', self._time),
                     ('Multi Position', self._positions),
                     ('Exposure Settings', self._exposure)):
            sizer.Add(StaticTextLine(self, label=conf[0]),
                      flag=wx.EXPAND|wx.ALL, border=border)
            sizer.Add(conf[1], flag=wx.EXPAND|wx.ALL, border=border)
        self.SetSizer(sizer)

    def PrepareExperiment(self, save_fpath):
        num_t = self._time.GetNumTimePoints()
        if numReps > 1:
            time_interval = self.time_control.GetTimeInterval()
        else:
            time_interval = 0.0

        num_z = self._z_stack.GetNumTimePoints()
        if num_z == 1:
            zPositioner = None
            altBottom = None
            zHeight = None
            sliceHeight = None
        else:
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

        experiment = True
        return experiment


class SIMExperimentPanel(WidefieldExperimentPanel):
    NAME = 'Structured Illumination'
    def __init__(self, *args, **kwargs):
        super(SIMExperimentPanel, self).__init__(*args, **kwargs)
        self._sim_control = SIMSettingsPanel(self)

        sizer = self.GetSizer()
        border = self.GetFont().GetPointSize() /2
        sizer.Add(StaticTextLine(self, label="SIM settings"),
                  flag=wx.EXPAND|wx.ALL, border=border)
        sizer.Add(self._sim_control, flag=wx.EXPAND|wx.ALL, border=border)


class RotatorSweepExperimentPanel(AbstractExperimentPanel):
    NAME = 'Rotator Sweep'
    def __init__(self, *args, **kwargs):
        super(RotatorSweepExperimentPanel, self).__init__(*args, **kwargs)
        self._exposure = ExposureSettingsPanel(self)
        self._sweep = RotatorSweepSettingsPanel(self)

        sizer = wx.BoxSizer(wx.VERTICAL)
        border = self.GetFont().GetPointSize() /2
        for conf in (('Exposure Settings', self._exposure),
                     ('Rotator Sweep', self._sweep)):
            sizer.Add(StaticTextLine(self, label=conf[0]),
                      flag=wx.EXPAND|wx.ALL, border=border)
            sizer.Add(conf[1], flag=wx.EXPAND|wx.ALL, border=border)
        self.SetSizer(sizer)


class ZSettingsPanel(wx.Panel):
    """
    TODO: pick ideal slice height for microscope configuration
    TODO: there were workarounds for 2D that set values to 1e-6 if height was 0
    TODO: z slice set to zero should be minimum step of z stage
    TODO: read saved z settings from cockpit
    """
    @enum.unique
    class Position(enum.Enum):
        CENTER = 'Current is centre'
        BOTTOM = 'Current is bottom'
        SAVED = 'Saved top/bottom'

    def __init__(self, parent, settings={}, *args, **kwargs):
        super(ZSettingsPanel, self).__init__(parent, *args, **kwargs)

        ## TODO: this should some config (maybe last used)
        default_stack_height = '90'
        default_slice_height = '100'

        self._stack_height = wx.TextCtrl(self, value=default_stack_height)
        self._slice_height = wx.TextCtrl(self, value=default_slice_height)
        self._number_slices = wx.SpinCtrl(self, min=1, max=(2**31)-1, initial=1)
        self._number_slices.Bind(wx.EVT_SPINCTRL, self.OnNumberSlicesChange)
        self._position = EnumChoice(self, choices=self.Position,
                                    default=self.Position.CENTER)
        self._position.Bind(wx.EVT_CHOICE, self.OnPositionChoice)

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        border = self.GetFont().GetPointSize() /2

        for conf in (('Number Z slices', self._number_slices),
                     ('Slice height (µm)', self._slice_height),
                     ('Stack height (µm)', self._stack_height)):
            sizer.Add(wx.StaticText(self, label=conf[0]),
                      flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL, border=border)
            sizer.Add(conf[1], flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL,
                      border=border)

        sizer.Add(self._position, flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL,
                  border=border)

        self.SetSizer(sizer)

    def OnNumberSlicesChange(self, event):
        if self._position.GetEnumSelection() == self.Position.SAVED:
            height = self.GetStackHeight() / self.GetNumTimePoints()
            self._slice_height.Value = '%f' % height
        else:
            height = self.GetSliceHeight() * self.GetNumTimePoints()
            self._stack_height.Value = '%f' % height

    def OnPositionChoice(self, event):
        if self._position.GetEnumSelection() == self.Position.SAVED:
            self._stack_height.Disable()
            ## TODO: set it correct
        else:
            self._stack_height.Enable()

    def GetStackHeight(self):
        return float(self._stack_height.Value)

    def GetSliceHeight(self):
        ## TODO: if slice height is zero, pick the smallest z step
        ## (same logic what we do with time).  But shold we do this
        ## here or should we do it in experiment?
        return float(self._slice_height.GetValue())

    def GetNumTimePoints(self):
        return int(self._number_slices.GetValue())


class TimeSettingsPanel(wx.Panel):
    def __init__(self, *args, **kwargs):
        super(TimeSettingsPanel, self).__init__(*args, **kwargs)
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        border = self.GetFont().GetPointSize() /2

        self._n_points = wx.SpinCtrl(self, min=1, max=(2**31)-1, initial=1)
        self._n_points.Bind(wx.EVT_SPINCTRL, self.UpdateDisplayedEstimate)
        self._interval = wx.TextCtrl(self, value='0')
        self._interval.Bind(wx.EVT_TEXT, self.UpdateDisplayedEstimate)
        self._total = wx.StaticText(self, label='Estimate')

        for conf in (('Number timepoints', self._n_points),
                     ('Time interval (s)', self._interval)):
            sizer.Add(wx.StaticText(self, label=conf[0]),
                      flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL, border=border)
            sizer.Add(conf[1], flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL,
                      border=border)

        sizer.Add(self._total, flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL,
                  border=border)

        self.SetSizer(sizer)

    def UpdateDisplayedEstimate(self, event):
        total_sec = self.GetNumTimePoints() * self.GetTimeInterval()
        if total_sec < 1.0:
            desc = '1 second'
        elif total_sec < 60.0:
            desc = '%d seconds' % round(total_sec)
        else:
            total_min = total_sec / 60.0
            total_hour = total_sec / 3600.0
            if total_hour < 1:
                desc = '%d minutes and %d seconds' % (total_min, total_sec)
            else:
                desc = '%d hours and %d minutes' % (total_hour, total_min)
        self._total.SetLabelText('Estimated ' + desc)
        self.Fit()

    def GetNumTimePoints(self):
        return int(self._n_points.GetValue())

    def GetTimeInterval(self):
        try:
            return float(self._interval.GetValue())
        except ValueError:
            if self._interval.GetValue() == '':
                return 0.0
            else:
                raise


class PositionSettingsPanel(wx.Panel):
    def __init__(self, *args, **kwargs):
        super(PositionSettingsPanel, self).__init__(*args, **kwargs)
        # sites to visit
        # optimize route
        # delay before imaging


class ExposureSettingsPanel(wx.Panel):
    def __init__(self, *args, **kwargs):
        super(ExposureSettingsPanel, self).__init__(*args, **kwargs)

        self._update = wx.Button(self, label='Update exposure settings')
        self._update.Bind(wx.EVT_BUTTON, self.OnUpdateSettings)

        self._simultaneous = wx.CheckBox(self, label='Simultaneous imaging')
        self._simultaneous.Bind(wx.EVT_CHECKBOX, self.OnSimultaneousCheck)

        ## TODO: read this from configuration
        cameras = ['west', 'east']
        lights = ['ambient', '405', '488', '572', '604']
        self._exposures = {}
        for camera in cameras:
            this_camera_exposures = {}
            for light in lights:
                exposure = wx.TextCtrl(self, value='')
                this_camera_exposures[light] = exposure
            self._exposures[camera] = this_camera_exposures
        self.OnUpdateSettings(None)

        sizer = wx.BoxSizer(wx.VERTICAL)
        border = self.GetFont().GetPointSize() /2
        grid = wx.FlexGridSizer(rows=len(cameras)+1, cols=len(lights)+1,
                                vgap=1, hgap=1)
        grid.Add((0,0))
        for light in lights:
            grid.Add(wx.StaticText(self, label=light),
                     flag=wx.ALIGN_CENTER_HORIZONTAL|wx.ALL^wx.BOTTOM,
                     border=border)
        for camera in cameras:
            grid.Add(wx.StaticText(self, label=camera),
                     flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL^wx.RIGHT, border=border)
            for light in lights:
                grid.Add(self._exposures[camera][light], border=border)
        sizer.Add(grid)
        row1 = wx.BoxSizer(wx.HORIZONTAL)
        row1.Add(self._update, flag=wx.ALL|wx.ALIGN_CENTER_VERTICAL,
                 border=border)
        row1.Add(self._simultaneous, flag=wx.ALL|wx.ALIGN_CENTER_VERTICAL,
                 border=border)
        sizer.Add(row1)

        self.SetSizer(sizer)

    def OnUpdateSettings(self, event):
        pass

    def OnSimultaneousCheck(self, event):
        for x in list(self._exposures.values())[1:]:
            print (x)
            for ctrl in x.values():
                ctrl.Enable(not event.IsChecked())


class SIMSettingsPanel(wx.Panel):
    @enum.unique
    class Type(enum.Enum):
        TwoDim = '2D SIM'
        ThreeDim = '3D SIM'

    @enum.unique
    class CollectionOrder(enum.Enum):
        ZAP = 'Z, Angle, Phase'
        ZPA = 'Z, Phase, Angle'

    def __init__(self, *args, **kwargs):
        super(SIMSettingsPanel, self).__init__(*args, **kwargs)
        from cockpit.experiment.structuredIllumination import COLLECTION_ORDERS

        self._type = EnumChoice(self, choices=self.Type,
                                default=self.Type.ThreeDim)
        self._order = EnumChoice(self, choices=self.CollectionOrder,
                                 default=self.CollectionOrder.ZAP)
        self._angles = wx.SpinCtrl(self, min=1, max=(2**31)-1, initial=3)
        lights = ['ambient', '405', '488', '572', '604']

        border = self.GetFont().GetPointSize() /2
        sizer = wx.BoxSizer(wx.VERTICAL)

        row1_sizer = wx.BoxSizer(wx.HORIZONTAL)
        for conf in (('Type', self._type),
                     ('Collection order', self._order),
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


class RotatorSweepSettingsPanel(wx.Panel):
    def __init__(self, *args, **kwargs):
        super(RotatorSweepSettingsPanel, self).__init__(*args, **kwargs)

        self._n_steps = wx.SpinCtrl(self, min=1, max=(2**31)-1, initial=100)
        self._start_v = wx.TextCtrl(self, value='0.0')
        self._max_v = wx.TextCtrl(self, value='10.0')
        self._settling_time = wx.TextCtrl(self, value='0.1')

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        border = self.GetFont().GetPointSize() /2
        for conf in (('Number of steps', self._n_steps),
                     ('Start V', self._start_v),
                     ('Max V', self._max_v),
                     ('Settling time (s)', self._settling_time)):
            sizer.Add(wx.StaticText(self, label=conf[0]),
                      flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL, border=border)
            sizer.Add(conf[1] ,flag=wx.ALIGN_CENTER_VERTICAL|wx.ALL,
                      border=border)

        self.SetSizer(sizer)


class DataLocationPanel(wx.Panel):
    """Two rows control to select directory and enter a filename template.
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

        self.SetSizer(sizer)

    def SetText(self, text):
        self.text.SetLabelText(text)
        self.Layout()


class EnumChoice(wx.Choice):
    """Convenience class to built a choice control from a menu.

    The choices must be an enum with unique values, the values must be
    strings, and the default must be specified and a valid element in
    the enum.

    """
    def __init__(self, parent, choices, default, *args, **kwargs):
        choices_str = [x.value for x in choices]
        super(EnumChoice, self).__init__(parent, choices=choices_str,
                                         *args, **kwargs)
        self._enum = choices
        for i, choice in enumerate(choices):
            if choice == default:
                self.SetSelection(i)
                break
        else:
            raise RuntimeError('default %s is not a choice' % default)

    def GetEnumSelection(self):
        return self._enum(self.GetString(self.GetSelection()))

    def SetEnumSelection(self, choice):
        self.SetSelection(self.FindString(self._enum(choice).value))


class StaticTextLine(wx.Control):
    """A Static Line with a title to split panels in a vertical orientation.

    In the ideal case, we would StaticBoxes for this but that looks
    pretty awful and broken unless used with StaticBoxSizer
    https://trac.wxwidgets.org/ticket/18253

    TODO: Maybe have the text centered horizontal and a static line on
    each side.
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


if __name__ == "__main__":
    app = wx.App()
    frame = ExperimentFrame(None)

    # import wx.lib.inspection
    # wx.lib.inspection.InspectionTool().Show()

    frame.Show()
    app.MainLoop()
