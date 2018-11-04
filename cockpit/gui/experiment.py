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

TODO: there should be an event for when new devices are added/removed.
For example, adding or removing a new z stage, so that the interface
does not give options that no longer exist.

TODO: disable multiposition if there's no xy stage

TODO: should location of saved data part of the experiment settings?

"""

import collections
import decimal
import enum
import os.path
import sys
import time

import wx

import cockpit.depot
import cockpit.events
import cockpit.experiment
import cockpit.interfaces.stageMover


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
        for id, handler in ((wx.ID_OPEN, self.OnOpen),
                            (wx.ID_SAVEAS, self.OnSaveAs),
                            (wx.ID_CLOSE, self.OnClose)):
            file_menu.Append(id)
            self.Bind(wx.EVT_MENU, handler, id=id)
        menu_bar.Append(file_menu, '&File')
        self.MenuBar = menu_bar

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
        sizer.Add(self._book, wx.SizerFlags().Expand().Border())
        sizer.AddStretchSpacer()
        for ctrl in (StaticTextLine(self, label="Data Location"),
                      self._data_location, self._status):
            sizer.Add(ctrl, wx.SizerFlags().Expand().Border())

        buttons_sizer = wx.BoxSizer(wx.HORIZONTAL)
        for button in (self._run, self._abort):
            buttons_sizer.Add(button, wx.SizerFlags().Border())
        sizer.Add(buttons_sizer, wx.SizerFlags().Right().Border())

        self.SetSizerAndFit(sizer)


    def OnRunButton(self, event):
        self.OnExperimentStart()
        self._status.Text = 'Preparing experiment'

        ## TODO: rethink this error handling
        def cancel_preparation(msg):
            self._status.Text = 'Failed to start experiment:\n' + msg
            self.OnExperimentEnd()

        try:
            fpath = self.GetSavePath()
        except Exception as e:
            cancel_preparation(str(e))
            return

        if not self.CheckFileOverwrite(fpath):
            cancel_preparation('user cancelled to not overwrite file')
            return

        experiment_panel = self._book.CurrentPage
        try:
            ## TODO: how long does this takes?  Is it bad we are blocking?
            self.experiment = experiment_panel.PrepareExperiment(fpath)
        except Exception as e:
            cancel_preparation(str(e))
            raise

        self._status.Text = 'Experiment starting'
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

        self._status.Text = 'Aborting experiment'
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
        filepath = dialog.Path
        print(filepath)

    def OnSaveAs(self, event):
        dialog = wx.FileDialog(self, message='Select file to save experiment',
                               style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT)
        if dialog.ShowModal() != wx.ID_OK:
            return
        filepath = dialog.Path
        print(filepath)

    def OnClose(self, event):
        ## If this is a close event (closing the window) we may not be
        ## able to veto the close.
        if ((event.EventType == wx.wxEVT_CLOSE_WINDOW and event.CanVeto())
            and self.IsExperimentRunning()):
            ## Only inform that experiment is running.  Do not give an
            ## option to abort experiment to avoid accidents.
            caption = "Experiment is running."
            message = ("This experiment is still running."
                       " Abort the experiment first.")
            msg = wx.MessageBox(message=message, caption=caption, parent=None,
                          style=wx.OK|wx.CENTRE|wx.ICON_ERROR)
            event.Veto()
        else:
            ## TODO: we may end here because we can't veto the
            ## closing.  In that case, abort the experiment.

            ## TODO: this needs to be set automatically at
            ## subscription, and not at close and not in a destructor.
            cockpit.events.unsubscribe(cockpit.events.EXPERIMENT_COMPLETE,
                                       self.OnExperimentEnd)

            self.Destroy()

    def IsExperimentRunning(self):
        return self.experiment is not None and self.experiment.is_running()

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
            self._status.Text = "selected filepath '%s' is a directory" % fpath
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
                self._status.Text = ("selected filepath '%s' already exists"
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
        self._sites = MultiSiteSettingsPanel(self)
        self._exposure = ExposureSettingsPanel(self)

        sizer = wx.BoxSizer(wx.VERTICAL)
        for label, ctrl in (('Z Stack', self._z_stack),
                            ('Time Series', self._time),
                            ('Multi Site', self._sites),
                            ('Exposure Settings', self._exposure)):
            sizer.Add(StaticTextLine(self, label=label),
                      wx.SizerFlags().Expand().Border())
            sizer.Add(ctrl, wx.SizerFlags().Expand().Border())
        self.Sizer = sizer

    def PrepareExperiment(self, save_fpath):
        num_t = self._time.NumTimePoints
        if num_t > 1:
            time_interval = self.time_control.TimeInterval
        else:
            time_interval = 0.0 # XXX: or None?

        ## TODO: we need to change Experiment, so that we don't have
        ## to pass all of this when it's not a Z stack experiment.
        z_settings = {
            'zPositioner' : self._z_stack.Stage,
            'altBottom' : self._z_stack.GetBottomZ(),
            'zHeight' : self._z_stack.StackHeight,
            'sliceHeight' : self._z_stack.SliceHeight,
        }

        exposureSettings = self._exposure.GetExposures()
        cameras = []
        lights = []
        for exp_cameras, lights_times in exposureSettings:
            cameras.extend(exp_cameras)
            lights.extend([light for light, time in lights_times])
        image_settings = {
            'cameras': cameras,
            'lights' : lights,
            'exposureSettings' : exposureSettings,
        }
        params = {'numReps' : num_t, 'repDuration' :time_interval,
                  **z_settings, **image_settings,
                  'savePath' : save_fpath}
        print(params)
        from cockpit.experiment.zStack import ZStackExperiment
        experiment = ZStackExperiment(numReps=num_t, repDuration=time_interval,
                                      **z_settings, **image_settings,
                                      savePath=save_fpath)

        if len(self._sites.Sites) > 0:
            ## TODO: the plan is to make use of MultiSiteExperiment
            ## (or SynchronisedExperiments) here.  And even if there's
            ## only one site saved, that's still multi-site, and is
            ## effectively different from doing the experiment on the
            ## current location.
            raise NotImplementedError('no support for multi-site yet')

        return experiment


class SIMExperimentPanel(WidefieldExperimentPanel):
    NAME = 'Structured Illumination'
    def __init__(self, *args, **kwargs):
        super(SIMExperimentPanel, self).__init__(*args, **kwargs)
        self._sim_control = SIMSettingsPanel(self)

        self.Sizer.Add(StaticTextLine(self, label="SIM settings"),
                       wx.SizerFlags().Expand().Border())
        self.Sizer.Add(self._sim_control, wx.SizerFlags().Expand().Border())


class RotatorSweepExperimentPanel(AbstractExperimentPanel):
    NAME = 'Rotator Sweep'
    def __init__(self, *args, **kwargs):
        super(RotatorSweepExperimentPanel, self).__init__(*args, **kwargs)
        self._exposure = ExposureSettingsPanel(self)
        self._sweep = RotatorSweepSettingsPanel(self)

        sizer = wx.BoxSizer(wx.VERTICAL)
        for label, ctrl in (('Exposure Settings', self._exposure),
                            ('Rotator Sweep', self._sweep)):
            sizer.Add(StaticTextLine(self, label=label),
                      wx.SizerFlags().Expand().Border())
            sizer.Add(ctrl, wx.SizerFlags().Expand().Border())
        self.Sizer = sizer


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

    def __init__(self, *args, **kwargs):
        super(ZSettingsPanel, self).__init__(*args, **kwargs)

        self._stages = cockpit.depot.getSortedStageMovers().get(2, [])
        if len(self._stages) == 0:
            self.Disable()

        ## TODO: this should be some config (maybe last used)
        default_stack_height = '0.1'
        default_slice_height = '0.1'

        self._stack_height = wx.TextCtrl(self, value=default_stack_height)
        self._slice_height = wx.TextCtrl(self, value=default_slice_height)
        self._number_slices = wx.SpinCtrl(self, min=1, max=(2**31)-1, initial=1)
        self._number_slices.Bind(wx.EVT_SPINCTRL, self.OnNumberSlicesChange)
        self._position = EnumChoice(self, choices=self.Position,
                                    default=self.Position.CENTER)
        self._position.Bind(wx.EVT_CHOICE, self.OnPositionChoice)

        self._mover = wx.Choice(self, choices=[x.name for x in self._stages])
        self._mover.Selection = 0

        sizer = wx.BoxSizer(wx.VERTICAL)

        row1 = wx.BoxSizer(wx.HORIZONTAL)
        for label, ctrl in (('Number Z slices', self._number_slices),
                            ('Slice height (µm)', self._slice_height),
                            ('Stack height (µm)', self._stack_height)):
            row1.Add(wx.StaticText(self, label=label),
                     wx.SizerFlags().Centre().Border())
            row1.Add(ctrl, wx.SizerFlags().Centre().Border())
        row1.Add(self._position, wx.SizerFlags().Centre().Border())
        sizer.Add(row1)

        row2 = wx.BoxSizer(wx.HORIZONTAL)
        for label, ctrl in (('Z Mover', self._mover), ):
            row2.Add(wx.StaticText(self, label=label),
                     wx.SizerFlags().Centre().Border())
            row2.Add(ctrl, wx.SizerFlags().Centre().Border())
        sizer.Add(row2)

        self.Sizer = sizer

    ## TODO: we need a class that specifies the whole Z, this is not
    ## good and only makes sense because that's what the current
    ## Experiment class expects:
    def GetBottomZ(self):
        if self._UseSavedZ():
            raise NotImplementedError()
        else:
            current_z = cockpit.interfaces.stageMover.getPositionForAxis(2)
            if self._position.EnumSelection == self.Position.BOTTOM:
                return current_z
            else:
                return current_z - (float(self.StackHeight) /2)

    def _UseSavedZ(self):
        return self._position.EnumSelection == self.Position.SAVED

    def OnNumberSlicesChange(self, event):
        if self._UseSavedZ():
            height = self.StackHeight / self.NumTimePoints
            self._slice_height.Value = '%f' % height
        else:
            height = self.SliceHeight * self.NumTimePoints
            self._stack_height.Value = '%f' % height

    def OnPositionChoice(self, event):
        if self._UseSavedZ():
            self._stack_height.Disable()
            ## TODO: set the height using the saved positions
        else:
            self._stack_height.Enable()

    @property
    def StackHeight(self):
        return float(self._stack_height.Value)

    @property
    def SliceHeight(self):
        ## TODO: if slice height is zero, pick the smallest z step
        ## (same logic what we do with time).  But shold we do this
        ## here or should we do it in experiment?
        return float(self._slice_height.Value)

    @property
    def NumSlices(self):
        return int(self._number_slices.Value)

    @property
    def Stage(self):
        return self._stages[self._mover.Selection]


class TimeSettingsPanel(wx.Panel):
    def __init__(self, *args, **kwargs):
        super(TimeSettingsPanel, self).__init__(*args, **kwargs)
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        border = self.Font.PointSize /2

        self._n_points = wx.SpinCtrl(self, min=1, max=(2**31)-1, initial=1)
        self._n_points.Bind(wx.EVT_SPINCTRL, self.UpdateDisplayedEstimate)
        self._interval = wx.TextCtrl(self, value='0')
        self._interval.Bind(wx.EVT_TEXT, self.UpdateDisplayedEstimate)
        self._total = wx.StaticText(self, label='Estimate')

        for label, ctrl in (('Number timepoints', self._n_points),
                            ('Time interval (s)', self._interval)):
            sizer.Add(wx.StaticText(self, label=label),
                      wx.SizerFlags().Centre().Border())
            sizer.Add(ctrl, wx.SizerFlags().Centre().Border())

        sizer.Add(self._total, wx.SizerFlags().Centre().Border())

        self.Sizer = sizer

    def UpdateDisplayedEstimate(self, event):
        total_sec = self.NumTimePoints() * self.TimeInterval()
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
        self._total.LabelText = 'Estimated ' + desc
        self.Fit()

    @property
    def NumTimePoints(self):
        return int(self._n_points.Value)

    @property
    def TimeInterval(self):
        try:
            return float(self._interval.Value)
        except ValueError:
            if self._interval.Value == '':
                return 0.0
            else:
                raise


class MultiSiteSettingsPanel(wx.Panel):
    def __init__(self, *args, **kwargs):
        super(MultiSiteSettingsPanel, self).__init__(*args, **kwargs)
        self._sites = []

        self._text = wx.TextCtrl(self, value='')
        ## TODO: later we should add support to manually type the
        ## sites to visit.
        self._text.Disable()

        self._select = wx.Button(self, label='Change Selection')
        self._select.Bind(wx.EVT_BUTTON, self.OnSelectSites)

        cockpit.events.subscribe(cockpit.events.SITE_DELETED,
                                 self.OnSiteDeleted)

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(wx.StaticText(self, label='Selected Sites'),
                  wx.SizerFlags().Border().Center())
        sizer.Add(self._text, wx.SizerFlags(1).Expand().Border())
        sizer.Add(self._select, wx.SizerFlags().Border())
        self.Sizer = sizer

    def OnSelectSites(self, event):
        selected = []
        unselected = []
        for site in cockpit.interfaces.stageMover.getAllSites():
            if site in self.Sites:
                selected.append(site)
            else:
                unselected.append(site)
        all_sites = selected + unselected

        order = (list(range(len(selected)))
                 + list(range(~len(selected), ~len(all_sites), -1)))
        message = 'Select sites to visit and imaging order'
        dialog = SitesRearrangeDialog(self, message=message, order=order,
                                      sites=all_sites)
        if dialog.ShowModal() == wx.ID_OK:
            self.Sites = dialog.List.CheckedSites

    def OnSiteDeleted(self, deleted_site):
        if deleted_site in self.Sites:
            self.Sites = [site for site in self.Sites if site != deleted_site]

    @property
    def Sites(self):
        return self._sites

    @Sites.setter
    def Sites(self, sites):
        self._sites = sites
        ## TODO: support ranges for long consecutive site ids
        self._text.Value = ', '.join([str(x) for x in self._sites])


class SitesRearrangeDialog(wx.Dialog):
    """Modelled after wx.RearrangeDialog but for stage site.
    """
    def __init__(self, parent, message, title=wx.EmptyString, order=[],
                 sites=[], pos=wx.DefaultPosition, name='SitesRearrangeDlg'):
        super(SitesRearrangeDialog, self).__init__(parent, id=wx.ID_ANY,
                                                   title=title, pos=pos,
                                                   size=wx.DefaultSize,
                                                   style=(wx.DEFAULT_DIALOG_STYLE
                                                          |wx.RESIZE_BORDER),
                                                   name=name)
        self._ctrl = SitesRearrangeCtrl(self, order=order, sites=sites)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(self, label=message), wx.SizerFlags().Border())
        sizer.Add(self._ctrl, wx.SizerFlags(1).Expand().Border())
        sizer.Add(self.CreateSeparatedButtonSizer(wx.OK|wx.CANCEL),
                  wx.SizerFlags().Expand().Border())
        self.SetSizerAndFit(sizer)

    @property
    def List(self):
        return self._ctrl.List
    @property
    def Order(self):
        return self._ctrl.List.CurrentOrder


class SitesRearrangeCtrl(wx.Panel):
    """Modelled after wx.RearrangeCtrl but for stage sites.
    """
    def __init__(self, parent, id=wx.ID_ANY, pos=wx.DefaultPosition,
                 size=wx.DefaultSize, order=[], sites=[], style=0,
                 validator=wx.DefaultValidator, name='SitesRearrangeList'):
        super(SitesRearrangeCtrl, self).__init__(parent, id=id, pos=pos,
                                                 size=size,
                                                 style=wx.TAB_TRAVERSAL,
                                                 name=name)

        ## Because of https://github.com/wxWidgets/Phoenix/issues/1052
        ## each time we make major changes to the order, e.g., when we
        ## click optimise, we need to create a new list.  Hence, we
        ## have this factory.
        def list_factory(order, sites):
            return SitesRearrangeList(self, order=order, sites=sites,
                                      style=style, validator=validator)
        self._list_factory = list_factory
        self._list = self._list_factory(order, sites)

        move_up = wx.Button(self, id=wx.ID_UP)
        move_up.Bind(wx.EVT_BUTTON, self.OnMove)
        move_down = wx.Button(self, id=wx.ID_DOWN)
        move_down.Bind(wx.EVT_BUTTON, self.OnMove)

        optimise = wx.Button(self, label='Optimise')
        optimise.Bind(wx.EVT_BUTTON, self.OnOptimise)
        select_all = wx.Button(self, label='Select All')
        select_all.Bind(wx.EVT_BUTTON, self.OnSelectAll)
        deselect_all = wx.Button(self, label='Deselect All')
        deselect_all.Bind(wx.EVT_BUTTON, self.OnDeselectAll)

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(self._list, wx.SizerFlags(1).Expand().Border(wx.RIGHT))
        buttons_col = wx.BoxSizer(wx.VERTICAL)
        for btn in (move_up, move_down, select_all, deselect_all, optimise):
            buttons_col.Add(btn, wx.SizerFlags().Centre().Border())

        sizer.Add(buttons_col, wx.SizerFlags().Centre().Border(wx.LEFT))
        self.Sizer = sizer

    @property
    def List(self):
        return self._list

    def OnOptimise(self, event):
        selected = []
        unselected = []
        for i, site in enumerate(self._list.Sites):
            if self._list.IsChecked(i):
                selected.append(site)
            else:
                unselected.append(site)

        optimised = cockpit.interfaces.stageMover.optimisedSiteOrder(selected)
        sites = optimised + unselected
        order = list(range(len(sites)))
        order[len(selected):] = [~x for x in order[len(selected):]]

        ## We can't just pass a new order and items.  We should be
        ## able to Set() the reordered sites and then only
        ## Check/Uncheck as required but that fails.  See
        ## https://github.com/wxWidgets/Phoenix/issues/1052 and
        ## https://trac.wxwidgets.org/ticket/18262
        ## The same bug means we can't Clear and then Append one item
        ## at a time.  So we just construct a new List each time as
        ## workaround.  When wxPython issue #1052 is fixed, we can:
        ##
        ## self._list.Clear()
        ## for item, pos in zip(sites, range(len(sites))):
        ##     self._list.Append(item)
        ##     self._list.Check(pos, pos < len(selected))
        old_list = self._list
        new_list = self._list_factory(order, sites)
        self.Sizer.Replace(old_list, new_list)
        old_list.Destroy()
        self._list = new_list
        self.Layout()

    def OnMove(self, event):
        if event.Id == wx.ID_UP:
            self.List.MoveCurrentUp()
        else:  # wx.ID_DOWN
            self.List.MoveCurrentDown()

    def OnSelectAll(self, event):
        self.List.CheckAll(True)
    def OnDeselectAll(self, event):
        self.List.CheckAll(False)


class SitesRearrangeList(wx.RearrangeList):
    """Convenience so we can pass Site objects instead of Strings.
    """
    def __init__(self, parent, id=wx.ID_ANY, pos=wx.DefaultPosition,
                 size=wx.DefaultSize, order=[], sites=[], style=0,
                 validator=wx.DefaultValidator, name='SitesRearrangeList'):
        items = [str(x.uniqueID) for x in sites]
        super(SitesRearrangeList, self).__init__(parent, id, pos, size, order,
                                                 items, style, validator, name)
        self._sites = sites

    @property
    def Sites(self):
        """Like `Items` but with Site objects.
        """
        ## CurrentOrder uses the index bit complement for unchecked items
        indices = [i if i >= 0 else ~i for i in self.CurrentOrder]
        return [self._sites[i] for i in indices]

    @property
    def CheckedSites(self):
        """Like `CheckedItems` but with Site objects.

        `CheckedItems` is a tuple and a not a list but we think that's
        a bug in wxPython since all other similar getters in the class
        return lists.  So we return list here to be coherent with the
        rest of the class.
        """
        ordered_sites = self.Sites
        return [ordered_sites[i] for i in self.CheckedItems]

    def CheckAll(self, check=True):
        for i in range(self.Count):
            self.Check(i, check)


class ExposureSettingsPanel(wx.Panel):
    def __init__(self, *args, **kwargs):
        super(ExposureSettingsPanel, self).__init__(*args, **kwargs)

        self._update = wx.Button(self, label='Update exposure settings')
        self._update.Bind(wx.EVT_BUTTON, self.OnUpdateSettings)

        self._simultaneous = wx.CheckBox(self, label='Simultaneous imaging')
        self._simultaneous.Bind(wx.EVT_CHECKBOX, self.OnSimultaneousCheck)

        ## TODO: read this from configuration
        self.cameras = sorted(cockpit.depot.getCameraHandlers(),
                              key=lambda c: c.name)
        self.lights = sorted(cockpit.depot.getLightSourceHandlers(),
                             key=lambda l: l.wavelength)

        self._exposures = ExposureSettingsCtrl(self, cameras=self.cameras,
                                               lights=self.lights)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._exposures)
        row1 = wx.BoxSizer(wx.HORIZONTAL)
        for ctrl in (self._update, self._simultaneous):
            row1.Add(ctrl, wx.SizerFlags().Border().Center())
        sizer.Add(row1)

        self.Sizer = sizer

    def OnUpdateSettings(self, event):
        raise NotImplementedError()

    def OnSimultaneousCheck(self, event):
        raise NotImplementedError()
        for x in list(self._exposures.values())[1:]:
            for ctrl in x.values():
                ctrl.Enable(not event.IsChecked())

    def GetExposures(self):
        return self._exposures.GetExposures()

class ExposureSettingsCtrl(wx.Control):
    def __init__(self, parent, id=wx.ID_ANY, pos=wx.DefaultPosition,
                 size=wx.DefaultSize, cameras=[], lights=[], style=0,
                 validator=wx.DefaultValidator, name='exposures'):
        super(ExposureSettingsCtrl, self).__init__(parent, id, pos, size,
                                                   wx.BORDER_NONE,
                                                   validator, name)

        ## Use OrderedDicts so that the order in the GUI matches the
        ## order of the returned exposures.
        self._exposures = collections.OrderedDict()
        for camera in cameras:
            this_camera_exposures = collections.OrderedDict()
            for light in lights:
                exposure = wx.TextCtrl(self, value='')
                this_camera_exposures[light] = exposure
            self._exposures[camera] = this_camera_exposures

        gap = int(wx.SizerFlags.GetDefaultBorder() /4)
        grid = wx.FlexGridSizer(rows=len(cameras)+1, cols=len(lights)+1,
                                 vgap=gap, hgap=gap)
        grid.Add((0,0))
        for light in lights:
            grid.Add(wx.StaticText(self, label=light.name),
                      wx.SizerFlags().Center().Border())
        for camera in cameras:
            grid.Add(wx.StaticText(self, label=camera.name),
                      wx.SizerFlags().Center().Border())
            for light in lights:
                grid.Add(self._exposures[camera][light])

        self.Sizer = grid

    def GetExposures(self):
        ## TODO: add support for simultaneous exposures
        exposures = []
        for camera in self._exposures.keys():
            this_exposures = self.GetCameraExposures(camera)
            if len(this_exposures) > 0:
                exposures.append(([camera], this_exposures))
        return exposures

    def GetCameraExposures(self, camera):
        exposures = []
        ## TODO: if camera is enabled
        for light, ctrl in self._exposures[camera].items():
            if ctrl.IsEmpty() or float(ctrl.Value) == 0.0:
                continue
            ## We want to use the text to construct the Decimal, and
            ## not convert it float first.
            exposures.append((light, decimal.Decimal(ctrl.Value)))
        return exposures

    def OnSimultaneousCheck(self, event):
        raise NotImplementedError()
        for x in list(self._exposures.values())[1:]:
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

        sizer = wx.BoxSizer(wx.VERTICAL)

        row1_sizer = wx.BoxSizer(wx.HORIZONTAL)
        for label, ctrl in (('Type', self._type),
                            ('Collection order', self._order),
                            ('Number of angles', self._angles)):
            row1_sizer.Add(wx.StaticText(self, label=label),
                           wx.SizerFlags().Centre().Border())
            row1_sizer.Add(ctrl, wx.SizerFlags().Centre().Border())
        sizer.Add(row1_sizer)

        grid = wx.FlexGridSizer(rows=2, cols=len(lights)+1, gap=(1,1))
        grid.Add((0,0))
        for l in lights:
            grid.Add(wx.StaticText(self, label=l),
                     wx.SizerFlags().Centre())
        grid.Add(wx.StaticText(self, label='Bleach compensation (%)'),
                 wx.SizerFlags().Centre().Border())
        for l in lights:
            grid.Add(wx.TextCtrl(self, value='0.0'))
        sizer.Add(grid)

        self.Sizer = sizer


class RotatorSweepSettingsPanel(wx.Panel):
    def __init__(self, *args, **kwargs):
        super(RotatorSweepSettingsPanel, self).__init__(*args, **kwargs)

        self._n_steps = wx.SpinCtrl(self, min=1, max=(2**31)-1, initial=100)
        self._start_v = wx.TextCtrl(self, value='0.0')
        self._max_v = wx.TextCtrl(self, value='10.0')
        self._settling_time = wx.TextCtrl(self, value='0.1')

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        for label, ctrl in (('Number of steps', self._n_steps),
                            ('Start V', self._start_v),
                            ('Max V', self._max_v),
                            ('Settling time (s)', self._settling_time)):
            sizer.Add(wx.StaticText(self, label=label),
                      wx.SizerFlags().Centre().Border())
            sizer.Add(ctrl, wx.SizerFlags().Centre().Border())
        self.Sizer = sizer


class DataLocationPanel(wx.Panel):
    """Two rows control to select directory and enter a filename template.
    """
    def __init__(self, *args, **kwargs):
        super(DataLocationPanel, self).__init__(*args, **kwargs)

        ## TODO: read default path from config
        self._dir = wx.DirPickerCtrl(self, path=os.getcwd())
        ## TODO: read default template from config
        self._template = wx.TextCtrl(self, value="{time}.mrc")

        grid = wx.FlexGridSizer(rows=2, cols=2, gap=(0,0))
        grid.AddGrowableCol(1, 1)
        for label, ctrl in (('Directory', self._dir),
                            ('Filename', self._template)):
            grid.Add(wx.StaticText(self, label=label),
                     wx.SizerFlags().Centre().Border(wx.LEFT))
            grid.Add(ctrl, wx.SizerFlags().Expand().Border(wx.RIGHT))
        self.Sizer = grid

    def GetPath(self, mapping):
        """Return path for a file after template interpolation.

        Args:
            mapping (dict): maps keys in the template string to their
                substitution value.  Same as :func:`str.format_map`.

        Raises:
            :class:`KeyError` if there are keys in the template
            filename missing from `mapping`.
        """
        dirname = self._dir.Path
        template = self._template.Value
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

        ## XXX: not sure about the status text.  We also have the
        ## space below the progress bar, left of the run and stop
        ## buttons.  But I feel like this should be seen as one panel
        ## with the progress bar.
        self._text = wx.StaticText(self, style=wx.ALIGN_CENTRE_HORIZONTAL,
                                   label='This is progress...')
        self._progress = wx.Gauge(self)

        sizer = wx.BoxSizer(wx.VERTICAL)
        for ctrl in (self._text, self._progress):
            sizer.Add(ctrl, wx.SizerFlags().Expand().Centre())
        self.Sizer = sizer

    @property
    def Text(self):
        return self._text.LabelText

    @Text.setter
    def Text(self, text):
        self._text.LabelText = text
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
        enum.unique(choices) # raise ValueError if there's duplicated values
        self._enum = choices
        try:
            self.Selection = [x for x in choices].index(default)
        except ValueError:
            ## index() may raise a ValueError but if the enum is
            ## missing, that's because default is another type.
            raise TypeError('default %s is not a %s' % (default, choices))

    @property
    def EnumSelection(self):
        return self._enum(self.StringSelection)

    @EnumSelection.setter
    def EnumSelection(self, choice):
        self.Selection = self.FindString(self._enum(choice).value)


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
        border = self.Font.PointSize
        sizer.Add(wx.StaticText(self, label=label),
                  wx.SizerFlags().Border(wx.RIGHT).Centre())
        sizer.Add(wx.StaticLine(self),
                  wx.SizerFlags(1).Border().Centre())
        self.Sizer = sizer


if __name__ == "__main__":
    app = wx.App()
    frame = ExperimentFrame(None)

    # import wx.lib.inspection
    # wx.lib.inspection.InspectionTool().Show()
    cockpit.interfaces.stageMover.initialize()
    frame.Show()
    app.MainLoop()
