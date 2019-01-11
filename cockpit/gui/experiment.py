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

TODO: some of the classes here, such as EnumChoice and InfoTextCtrl
may be of more general use so maybe we could move them to cockpit.gui.

"""

import collections
import decimal
import enum
import math
import os.path
import sys
import time

import wx

import cockpit.depot
import cockpit.events
import cockpit.experiment
import cockpit.experiment.experiment
import cockpit.gui
import cockpit.gui.guiUtils
import cockpit.gui.saveTopBottomPanel
import cockpit.interfaces.stageMover


class ExperimentFrame(wx.Frame):
    """Frame to contain an :class:`ExperimentPanel`

    Args:
        parent (wx.Window): parent window.  Can be `None` for top
            level windows.
        experiments (dict): keys are the experiment names to be show
            for selection and values the classes to construct them.
            The name is something we want to have configurable which
            is why this is a dict instead of having the name as class
            property.
        title (string): the frame title
        **kwargs: to pass forward to :class:`wx.Frame`
    """
    def __init__(self, parent, experiments={}, title="Experiment", **kwargs):
        super(ExperimentFrame, self).__init__(parent, title=title, **kwargs)

        self._experiment_panel = ExperimentPanel(self)
        for ex_name, panel_cls in experiments.items():
            self._experiment_panel.AddExperimentType(panel_cls(self), ex_name)

        menu_bar = wx.MenuBar()
        file_menu = wx.Menu()
        for id, handler in ((wx.ID_OPEN, self.OnOpen),
                            (wx.ID_SAVEAS, self.OnSaveAs),
                            (wx.ID_CLOSE, self.OnClose)):
            file_menu.Append(id)
            self.Bind(wx.EVT_MENU, handler, id=id)
        menu_bar.Append(file_menu, '&File')
        self.MenuBar = menu_bar

        self.Bind(wx.EVT_CLOSE, self.OnClose)

        sizer = wx.BoxSizer()
        sizer.Add(self._experiment_panel, wx.SizerFlags(1).Expand())
        self.SetSizerAndFit(sizer)

    def OnOpen(self, evt):
        dialog = wx.FileDialog(self, message='Select experiment to open',
                               style=wx.FD_OPEN|wx.FD_FILE_MUST_EXIST)
        if dialog.ShowModal() != wx.ID_OK:
            return
        filepath = dialog.Path
        print(filepath)

    def OnSaveAs(self, evt):
        dialog = wx.FileDialog(self, message='Select file to save experiment',
                               style=wx.FD_SAVE|wx.FD_OVERWRITE_PROMPT)
        if dialog.ShowModal() != wx.ID_OK:
            return
        filepath = dialog.Path
        print(filepath)

    def OnClose(self, evt):
        ## Since this frame represents an experiment that may be
        ## running, it should not be closed if the experiment is
        ## running.  To prevent the user from accidentally aborting
        ## the experiment by closing the window, we require the user
        ## to explicitly abort the experiment via the Abort button.
        ## However, if this is a CloseEvent we must check CanVeto
        ## which may prevent us from doing so.  Only CloseEvents have
        ## the CanVeto and Veto methods so we need to check the event
        ## type since we may not necessarily be handling a CloseEvent.
        ## Closing the window does send a CloseEvent but choosing
        ## "Close" from the frame menu or the Ctrl+w keyboard shortcut
        ## sends a MenuEvent.  We may even be handling other event
        ## types in the future.
        evt_has_vetoing_methods = evt.EventType == wx.wxEVT_CLOSE_WINDOW
        can_ignore_close = not evt_has_vetoing_methods or evt.CanVeto()

        if not self._experiment_panel.IsExperimentRunning():
            ## TODO: maybe ask about saving experiments settings?
            self.Destroy()
        elif can_ignore_close:
            caption = "Experiment is running."
            message = ("This experiment is still running."
                       " Abort the experiment first.")
            wx.MessageBox(message=message, caption=caption, parent=self,
                          style=wx.OK|wx.CENTRE|wx.ICON_ERROR)
            if evt_has_vetoing_methods:
                evt.Veto()
        else:
            try:
                self._experiment_panel.AbortExperiment()
            finally:
                self.Destroy()


class ExperimentPanel(wx.Panel):
    """Panel to select an Experiment type.

    This class deals with selecting an experiment type, the start of
    experiment, and display of experiment progress.  The actual
    experiment design is handled by its central Panel, each experiment
    type having its own.

    """
    def __init__(self, *args, **kwargs):
        super(ExperimentPanel, self).__init__(*args, **kwargs)
        self._experiment = None
        self._experiment_book = wx.Choicebook(self)
        self._data_location = DataLocationPanel(self)
        self._status = ExperimentStatusPanel(self)

        ## We have separate Run and Abort buttons instead of a toggle
        ## button.  A toggle button would make sense for Run/Pause but
        ## we can't really do that, we can only re-run the experiment.
        self._run_button = wx.Button(self, label='Run')
        self._run_button.Bind(wx.EVT_BUTTON, self._OnRunButton)
        self._abort_button = wx.Button(self, label='Abort')
        self._abort_button.Bind(wx.EVT_BUTTON, self._OnAbortButton)

        self._EnableExperimentControls()

        ## We don't need to to subscribe to USER_ABORT because an
        ## aborted experiment will still emit EXPERIMENT_COMPLETE
        ## after it has finish the abortion and cleanup.
        ## XXX: we could use the ExperimentEvtEmitter and only do this
        ## for our own experiment.
        emitter = cockpit.gui.CockpitEvtEmitter(self,
                                                cockpit.events.EXPERIMENT_COMPLETE)
        emitter.Bind(cockpit.gui.EVT_COCKPIT, self._OnExperimentEnd)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._experiment_book, wx.SizerFlags().Expand().Border())
        sizer.AddStretchSpacer()
        for ctrl in (StaticTextLine(self, label='Data Location'),
                      self._data_location, self._status):
            sizer.Add(ctrl, wx.SizerFlags().Expand().Border())

        buttons_sizer = wx.BoxSizer(wx.HORIZONTAL)
        for button in (self._run_button, self._abort_button):
            buttons_sizer.Add(button, wx.SizerFlags().Border())
        sizer.Add(buttons_sizer, wx.SizerFlags().Right().Border())

        self.Sizer = sizer

    def AddExperimentType(self, panel, name):
        panel.Reparent(self._experiment_book)
        self._experiment_book.AddPage(panel, text=name)

    def _EnableExperimentControls(self, enable=True):
        """Enable/Disable controls that change when experiment is running.

        This aggregates all the stuff that should be disabled when
        this experiment is running.

        1. There may be more than one experiment window.  Disabling
           the controls gives a quick visual hint of what experiment
           is running (the disabled controls will appear greyed).

        2. The window provides a display of the settings of the
           running experiment.  By disabling changes the user is
           prevented from accidentally changing it and ending up not
           knowing what the settings were.  If users wants to start
           preparing a new experiment they can open a new experiment
           window and modify that one.
        """
        self._experiment_book.Enable(enable)
        self._run_button.Enable(enable)
        self._abort_button.Enable(not enable)

    def RunExperiment(self):
        self._EnableExperimentControls(False)

        ## XXX: We need to do this before preparing the experiment
        ## because it is needed to construct the Experiment instance.
        ## Ideally, those things would be separate.

        ## TODO: how to get more path components from the current
        ## experiment panel?
        fpath = self.GetSavePath()
        if not self.CheckFileOverwrite(fpath):
            self._EnableExperimentControls()
            return

        try:
            self._PrepareExperiment(fpath)
        except Exception as e:
            import traceback
            #wx.MessageBox(str(e), caption='Failed to prepare experiment',
            wx.MessageBox(traceback.format_exc(), caption='Failed to prepare experiment',
                          parent=self, style=wx.OK|wx.CENTRE|wx.ICON_ERROR)
            self._EnableExperimentControls()
            return

        self._status.Experiment = self._experiment
        wx.CallAfter(self._experiment.run)

    def _PrepareExperiment(self, fpath):
        ## TODO: how long does this takes?  Is it bad we are blocking?
        experiment_panel = self._experiment_book.CurrentPage
        experiment = experiment_panel.PrepareExperiment(fpath)

        ## XXX: Should we really be forcing this?
        mover = cockpit.interfaces.stageMover.mover
        current_z = mover.axisToHandlers[2][mover.curHandlerIndex]
        innermost_z = mover.axisToHandlers[2][-1]
        if experiment.zPositioner != current_z:
            raise RuntimeError('Selected Z handler differs from current')
        if experiment.zPositioner != innermost_z:
            raise RuntimeError('Selected Z handler is not the innermost')

        self._experiment = experiment

    def _OnExperimentEnd(self, evt):
        self._EnableExperimentControls()

    def AbortExperiment(self):
        if self.IsExperimentRunning():
            self._experiment.onAbort()

    def _OnRunButton(self, evt):
        if cockpit.experiment.experiment.isRunning():
            message = ('Another experiment is still running. Only after that'
                       ' experiment finishes can this experiment be started.')
            wx.MessageBox(message, caption='An experiment is already running',
                          parent=self, style=wx.OK|wx.CENTRE|wx.ICON_ERROR)
        else:
            self.RunExperiment()

    def _OnAbortButton(self, evt):
        caption = 'Aborting experiment'
        message = 'Should the acquired data be discarded?'
        ## TODO: actually implement the discard of data.
        dialog = wx.MessageDialog(self, message=message, caption=caption,
                                  style=(wx.YES_NO|wx.CANCEL|wx.NO_DEFAULT
                                         |wx.ICON_EXCLAMATION))
        dialog.SetYesNoLabels('Discard', 'Keep')
        status = dialog.ShowModal()
        if status != wx.CANCEL:
            if status == wx.YES: # discard data
                raise NotImplementedError("don't know how to discard data yet")

            self.AbortExperiment()

    def IsExperimentRunning(self):
        return self._experiment is not None and self._experiment.is_running()

    def GetSavePath(self):
        ## TODO: format of time should be a configuration
        mapping = {
            'time' : time.strftime('%Y%m%d-%H%M%S', time.localtime())
        }
        ## TODO: get more mapping from the current experiment panel.
        try:
            fpath = self._data_location.GetPath(mapping)
        except KeyError as e:
            raise RuntimeError('missing path substitution value for %s' % e)
        return fpath

    def CheckFileOverwrite(self, fpath):
        """

        Returns:
            ``True`` if we can continue (either file does not exist or
            user is OK with overwriting it).  ``False`` otherwise
            (file is a directory or user does not want to overwrite).
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
    """
    def PrepareExperiment(self, save_fpath):
        """Prepare a :class:`cockpit.experiment.experiment.Experiment` to run.

        At the moment, this prepares the experiment which requires the
        filepath.  In the future, this should instead only generate
        the action table which is then used to create the experiment
        together with the file path (datasaver).  That's a lot more
        refactoring for the future.

        Args:
            save_fpath (str): filepath to save the image.

        Raises:
            :class:`RuntimeError` in case of failing

        TODO: I'm not a big fan of this raising exceptions for some of
        this not really exceptions such as existing files.  Maybe
        return None?

        """
        raise NotImplementedError('')


class WidefieldExperimentPanel(AbstractExperimentPanel):
    def __init__(self, *args, **kwargs):
        super(WidefieldExperimentPanel, self).__init__(*args, **kwargs)

        self._z_stack = ZSettingsPanel(self)
        self._time = TimeSettingsPanel(self)
        self._sites = MultiSiteSettingsPanel(self)
        self._exposure = ExposureSettingsPanel(self)

        if len(cockpit.depot.getSortedStageMovers().get(2, [])) == 0:
            self._z_stack.Disable()

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
            time_interval = None

        z_positions = self._z_stack.GetPositions()
        z_handler = self._z_stack.Stage
        exposures = self._exposure.GetExposures()

        if len(self._sites.Sites) > 0:
            ## TODO: the plan is to make use of MultiSiteExperiment
            ## (or SynchronisedExperiments) here.  And even if there's
            ## only one site saved, that's still multi-site, and is
            ## effectively different from doing the experiment on the
            ## current location.
            raise NotImplementedError('no support for multi-site yet')

        from cockpit.experiment.zStack import ZStackExperiment
        return ZStackExperiment(num_t, time_interval, z_handler, z_positions,
                                exposures, savePath=save_fpath)


class SIMExperimentPanel(WidefieldExperimentPanel):
    def __init__(self, *args, **kwargs):
        super(SIMExperimentPanel, self).__init__(*args, **kwargs)
        self._sim_control = SIMSettingsPanel(self)

        self.Sizer.Add(StaticTextLine(self, label="SIM settings"),
                       wx.SizerFlags().Expand().Border())
        self.Sizer.Add(self._sim_control, wx.SizerFlags().Expand().Border())


class RotatorSweepExperimentPanel(AbstractExperimentPanel):
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

    def PrepareExperiment(self, save_fpath):
        num_v_steps = self._sweep.NumSteps
        start_voltage = self._sweep.StartVoltage
        max_voltage = self._sweep.MaxVoltage
        settling_time = self._sweep.SettlingTime
        exposures = self._exposure.GetExposures()

        ## TODO: if this is always the same, then it's pointless.
        ## Either this can be done on the experiment class itself, or
        ## we need to add an option to the GUI to select the
        ## polarizer.
        polarizer_handler = depot.getHandlerWithName('SI polarizer')

        from cockpit.experiment.rotatorSweep import RotatorSweepExperiment
        experiment = RotatorSweepExperiment(polarizer_handler, settling_time,
                                            start_voltage, max_voltage,
                                            num_v_steps, exposures,
                                            savePath=save_fpath)
        return experiment


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

        default_step_size = '0.1'
        default_stack_height = '0.0'
        self._stages = cockpit.depot.getSortedStageMovers().get(2, [])

        self._number_slices = InfoTextCtrl(self, value='')
        self._step_size = wx.TextCtrl(self, value=default_step_size)
        self._stack_height = wx.TextCtrl(self, value=default_stack_height)
        for ctrl in (self._stack_height, self._step_size):
            ctrl.Bind(wx.EVT_KILL_FOCUS, self.OnStackChange)

        self._position = EnumChoice(self, choices=self.Position,
                                    default=self.Position.CENTER)
        self._position.Bind(wx.EVT_CHOICE, self.OnPositionChoice)

        self._mover = wx.Choice(self, choices=[x.name for x in self._stages])
        if len(self._stages):
            self._mover.Selection = cockpit.interfaces.stageMover.getCurHandlerIndex()

        self._UpdateNumberOfSlicesDisplay()

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer_flags = wx.SizerFlags().Centre().Border()

        for label, ctrl in (('Number Z slices', self._number_slices),
                            ('Step size (µm)', self._step_size),
                            ('Stack height (µm)', self._stack_height),):
            sizer.Add(wx.StaticText(self, label=label), sizer_flags)
            sizer.Add(ctrl, sizer_flags)

        sizer.Add(self._position, sizer_flags)

        for label, ctrl in (('Stage', self._mover),):
            sizer.Add(wx.StaticText(self, label=label), sizer_flags)
            sizer.Add(ctrl, sizer_flags)

        self.Sizer = sizer

    @property
    def StackHeight(self):
        return float(self._stack_height.Value)

    @property
    def StepSize(self):
        ## TODO: if slice height is zero, pick the smallest z step
        ## (same logic what we do with time).  But should we do this
        ## here or should we do it in experiment?  And do we even have
        ## that information (smallest z step size?)
        return float(self._step_size.Value)

    @property
    def Stage(self):
        if self._mover.Selection == wx.NOT_FOUND:
            return None
        else:
            return self._stages[self._mover.Selection]

    def GetPositions(self):
        step = self.StepSize
        height = self.StackHeight

        if step == 0:
            ## TODO: what should we do here?
            raise RuntimeError("step can't be zero")
        if height < 0:
            ## TODO: what to do?
            raise RuntimeError('stack height must be non-negative')

        bottom = None
        if self._UseSavedZ():
            bottom = cockpit.gui.saveTopBottomPanel.savedBottom
            if bottom > cockpit.gui.saveTopBottomPanel.savedTop:
                step = math.copysign(step, -1)
        else:
            current_z = cockpit.interfaces.stageMover.getPositionForAxis(2)
            if self._position.EnumSelection == self.Position.BOTTOM:
                bottom = current_z
            else: # Current is center
                bottom = current_z - (height /2.0)

        return cockpit.experiment.compute_z_positions(bottom, height, step)

    def _UseSavedZ(self):
        return self._position.EnumSelection == self.Position.SAVED

    def OnStackChange(self, evt):
        self._UpdateNumberOfSlicesDisplay()

    def _UpdateNumberOfSlicesDisplay(self):
        try:
            positions = self.GetPositions()
        except:
            ## TODO: what to display if there's an error somewhere?
            self._number_slices.Value = 'ERR'
            return

        self._number_slices.Value = str(len(positions))

    def OnPositionChoice(self, evt):
        if self._UseSavedZ():
            top = cockpit.gui.saveTopBottomPanel.savedTop
            bottom = cockpit.gui.saveTopBottomPanel.savedBottom
            if top is None or bottom is None:
                ## Doesn't seem like it's possible for saved top and
                ## bottom to currently not exist but there should be.
                ## When that happens, saved positions will probably be
                ## moved to stageMover and the raise should come from
                ## there.
                raise RuntimeError(("Can't use saved top/bottom without saved"
                                    " top and bottom positions."))
            self._stack_height.Value = str(abs(top - bottom))
            self._stack_height.Disable()
        else:
            self._stack_height.Enable()


class TimeSettingsPanel(wx.Panel):
    def __init__(self, *args, **kwargs):
        super(TimeSettingsPanel, self).__init__(*args, **kwargs)

        self._n_points = wx.SpinCtrl(self, min=1, max=(2**31)-1, initial=1)
        self._interval = wx.TextCtrl(self, value='0')

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        flags = wx.SizerFlags().Centre().Border()
        for label, ctrl in (('Number timepoints', self._n_points),
                            ('Time interval (s)', self._interval)):
            sizer.Add(wx.StaticText(self, label=label), flags)
            sizer.Add(ctrl, flags)

        self.Sizer = sizer

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

        emitter = cockpit.gui.CockpitEvtEmitter(self,
                                                cockpit.events.SITE_DELETED)
        emitter.Bind(cockpit.gui.EVT_COCKPIT, self.OnSiteDeleted)

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(wx.StaticText(self, label='Selected Sites'),
                  wx.SizerFlags().Border().Center())
        sizer.Add(self._text, wx.SizerFlags(1).Expand().Border())
        sizer.Add(self._select, wx.SizerFlags().Border())
        self.Sizer = sizer

    def OnSelectSites(self, evt):
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

    def OnSiteDeleted(self, evt):
        if len(self.Sites) > 0: # don't bother unless we actually have to handle
            all_sites = cockpit.interfaces.stageMover.getAllSites()
            self.Sites = [site for site in all_sites if site in self.Sites]

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

    def OnOptimise(self, evt):
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

    def OnMove(self, evt):
        if evt.Id == wx.ID_UP:
            self.List.MoveCurrentUp()
        else:  # wx.ID_DOWN
            self.List.MoveCurrentDown()

    def OnSelectAll(self, evt):
        self.List.CheckAll(True)
    def OnDeselectAll(self, evt):
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

        all_cameras = sorted(cockpit.depot.getCameraHandlers(),
                             key=lambda c: c.name)
        all_lights = sorted(cockpit.depot.getLightSourceHandlers(),
                            key=lambda l: l.wavelength)

        self._exposures = ExposureSettingsCtrl(self, cameras=all_cameras,
                                               lights=all_lights)

        self._update = wx.Button(self, label='Load current exposure times')
        self._update.Bind(wx.EVT_BUTTON, self.OnLoadCurrentTimes)
        self._simultaneous = wx.CheckBox(self, label='Simultaneous imaging')
        self._simultaneous.Bind(wx.EVT_CHECKBOX, self.OnSimultaneousCheck)

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(self._exposures)

        extras_col = wx.BoxSizer(wx.VERTICAL)
        for ctrl in (self._update, self._simultaneous):
            extras_col.Add(ctrl, wx.SizerFlags().Border().Center())
        sizer.Add(extras_col)

        self.Sizer = sizer

    def OnLoadCurrentTimes(self, evt):
        cameras = [c for c in self._exposures.Cameras if c.getIsEnabled()]
        lights = [l for l in self._exposures.Lights if l.getIsEnabled()]
        exposures = []
        for camera in cameras:
            for light in lights:
                exposure = cockpit.experiment.ExposureSettings()
                exposure.add_camera(camera)
                exposure.add_light(light, light.getExposureTime())
                exposures.append(exposure)
        self._exposures.SetExposures(exposures)

    def OnSimultaneousCheck(self, evt):
        if evt.IsChecked():
            self._exposures.EnableSimultaneousExposure()
        else:
            self._exposures.DisableSimultaneousExposure()

    def GetExposures(self):
        return self._exposures.GetExposures()


class ExposureSettingsCtrl(wx.Panel):
    """Grid to enter exposure times for cameras and lights.

    The order used on the cameras and lights is the order used in the
    display.  It is also the order used for the multiple returned
    :class:`cockpit.experiment.ExposureSettings`

    TODO: This control is quite limited in that the user can't
    actually change the order the images are acquired.  It also does
    not allow to have different images from the same camera with
    different light sources.  This limitation comes from older cockpit
    versions.

    """
    def __init__(self, parent, id=wx.ID_ANY, pos=wx.DefaultPosition,
                 size=wx.DefaultSize, cameras=[], lights=[], style=0,
                 validator=wx.DefaultValidator,
                 name='ExposureSettingsCtrl'):
        super(ExposureSettingsCtrl, self).__init__(parent, id, pos, size,
                                                   wx.TAB_TRAVERSAL, name)

        self._simultaneous = False
        self._exposures = collections.OrderedDict()
        for camera in cameras:
            self._exposures[camera] = collections.OrderedDict()
            for light in lights:
                self._exposures[camera][light] = wx.TextCtrl(self, value='')

        gap = int(wx.SizerFlags.GetDefaultBorder() /4)
        grid = wx.GridSizer(rows=len(cameras)+1, cols=len(lights)+1,
                            vgap=gap, hgap=gap)
        flags = wx.SizerFlags().Center().Border()
        grid.Add((0,0))
        for light in lights:
            grid.Add(wx.StaticText(self, label=light.name), flags)
        for camera in cameras:
            grid.Add(wx.StaticText(self, label=camera.name), flags)
            for light in lights:
                grid.Add(self._exposures[camera][light])

        self.Sizer = grid

    @property
    def Lights(self):
        return list(list(self._exposures.values())[0])

    @property
    def Cameras(self):
        return list(self._exposures.keys())

    def GetExposures(self):
        """Return list of ExposureSettings describing experiment.
        """
        if self._simultaneous:
            exposures = [self.GetCameraExposures(self.Cameras[0])]
        else:
            exposures = [self.GetCameraExposures(c) for c in self.Cameras]
        return [x for x in exposures if x is not None]

    def GetCameraExposures(self, camera):
        exposure = cockpit.experiment.ExposureSettings()
        for light, ctrl in self._exposures[camera].items():
            ## XXX: We distinguish between a value of zero and empty.
            ## If exposure is zero, an image will still acquired,
            ## there will just be no light.
            if ctrl.Value != '':
                exposure.add_light(light, decimal.Decimal(ctrl.Value))

        if len(exposure.exposures) > 0:
            exposure.add_camera(camera)
        else:
            exposure = None
        return exposure

    def _SyncLightCtrls(self, sync=True):
        for lights in self._exposures.values():
            for ctrl in lights.values():
                if sync:
                    ctrl.Bind(wx.EVT_TEXT, self._ChangeInAllCameras)
                else:
                    ctrl.Unbind(wx.EVT_TEXT)

    def _PropagateFirstLightExposure(self):
        """XXX: instead of setting value this uses events and so assumes
        """
        done = {light : False for light in self.Lights}
        for lights in self._exposures.values():
            for light, ctrl in lights.items():
                if done[light]:
                    continue
                if ctrl.Value != '':
                    text_evt = wx.CommandEvent(wx.wxEVT_TEXT, id=ctrl.Id)
                    text_evt.EventObject = ctrl
                    ctrl.ProcessEvent(text_evt)
                    done[light] = True

    def EnableSimultaneousExposure(self):
        self._SyncLightCtrls(sync=True)
        self._PropagateFirstLightExposure()
        self._simultaneous = True

    def DisableSimultaneousExposure(self):
        self._SyncLightCtrls(sync=False)
        self._simultaneous = False

    def _FindCameraLightFromCtrl(self, ctrl):
        for camera in self._exposures:
            for light in self._exposures[camera]:
                if self._exposures[camera][light] == ctrl:
                    return (camera, light)
        raise RuntimeError('unable to identify camera/light from ctrl')

    def _ChangeInAllCameras(self, evt):
        camera, light = self._FindCameraLightFromCtrl(evt.EventObject)
        value = evt.EventObject.Value
        for lights in self._exposures.values():
            lights[light].ChangeValue(value)

    def ClearAll(self):
        for camera in self._exposures:
            for ctrl in self._exposures[camera].values():
                ctrl.ChangeValue('')

    def SetExposures(self, exposures):
        """Apply changes

        Args:

            exposures (list of :class:`cockpit.experiment.ExposureSettings`):
                the only one that makes sense is to have one element
                per camera/light pair but this is not enforced.  The
                last one is applied.  The final result may also be
                affected by simultaneous.
        """
        self.ClearAll()
        for exposure in exposures:
            for camera in exposure.cameras:
                for light, time in exposure.exposures.items():
                    self._exposures[camera][light].SetValue(str(time))


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

        for ctrl in (self._start_v, self._max_v, self._settling_time):
            ctrl.Validator = cockpit.gui.guiUtils.FLOATVALIDATOR

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        for label, ctrl in (('Number of steps', self._n_steps),
                            ('Start V', self._start_v),
                            ('Max V', self._max_v),
                            ('Settling time (s)', self._settling_time)):
            sizer.Add(wx.StaticText(self, label=label),
                      wx.SizerFlags().Centre().Border())
            sizer.Add(ctrl, wx.SizerFlags().Centre().Border())
        self.Sizer = sizer

    @property
    def NumSteps(self):
        return int(self._n_steps.Value)
    @property
    def StartVoltage(self):
        return float(self._start_v.Value)
    @property
    def MaxVoltage(self):
        return float(self._max_v.Value)
    @property
    def SettlingTime(self):
        return float(self._max_v.Value)


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


class ExperimentStatusPanel(wx.Panel):
    """A panel with progress text and progress bar.

    Still not sure about the free text.  May be more useful to have
    multiple sections, such as estimated end time and estimated time
    left.

    """
    def __init__(self, *args, **kwargs):
        super(ExperimentStatusPanel, self).__init__(*args, **kwargs)
        self._experiment = None
        self._experiment_emitter = None
        self._text = wx.StaticText(self, style=wx.ALIGN_CENTRE_HORIZONTAL,
                                   label='...')
        self._progress = wx.Gauge(self)

        sizer = wx.BoxSizer(wx.VERTICAL)
        for ctrl in (self._text, self._progress):
            sizer.Add(ctrl, wx.SizerFlags().Expand().Centre())
        self.Sizer = sizer

    @property
    def Experiment(self):
        return self._Experiment

    @Experiment.setter
    def Experiment(self, experiment):
        ## XXX: what if this experiment is already running?
        ## XXX: what if the previous experiment was not finished?
        self._experiment = experiment
        if self._experiment_emitter is not None:
            self._experiment_emitter.Destroy()

        self._experiment_emitter = ExperimentEvtEmitter(self, self._experiment)
        events_to_handlers = {
            EVT_EXPERIMENT_START : self._OnExperimentStart,
            EVT_EXPERIMENT_STEP : self._OnExperimentStep,
            EVT_EXPERIMENT_CLEANUP : self._OnExperimentCleanup,
            EVT_EXPERIMENT_END : self._OnExperimentEnd,
        }
        for event, handler in events_to_handlers.items():
            self._experiment_emitter.Bind(event, handler)

    @property
    def Text(self):
        return self._text.LabelText

    @Text.setter
    def Text(self, text):
        self._text.LabelText = text
        self.Layout()

    def _OnExperimentStart(self, evt):
        self.Text = 'Starting experiment'

    def _OnExperimentStep(self, evt):
        ## TODO: figure out how to keep count of the images acquired
        ## and update gauge.  The event sends (light_name, msg, rgb)
        self.Text = 'something happened'

    def _OnExperimentCleanup(self, evt):
        self.Text = 'Cleaning up experiment'

    def _OnExperimentEnd(self, evt):
        self.Text = 'Experiment finished'


class InfoTextCtrl(wx.TextCtrl):
    """Just like a TextCtrl but always disabled meant for information.

    This is meant to be set programatically only.  It shows a value
    that can change easily by changes on other controls but that we
    don't want the user to control directly.  For example, the number
    of Z slices which should be set by modifying the z height or z
    step.

    We can't just use the `TE_READONLY` flag for style because that
    does not actually change the style (grey background).
    """
    def __init__(self, *args, **kwargs):
        super(InfoTextCtrl, self).__init__(*args, **kwargs)
        self.Disable()

    def Enable(enable=True):
        raise RuntimeError("An InfoTextCtrl should not be enabled")


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

    In the ideal case, we would use StaticBoxes for this but that
    looks pretty awful and broken unless used with StaticBoxSizer
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


EVT_EXPERIMENT_START = wx.PyEventBinder(wx.NewEventType())
EVT_EXPERIMENT_STEP = wx.PyEventBinder(wx.NewEventType())
EVT_EXPERIMENT_CLEANUP = wx.PyEventBinder(wx.NewEventType())
EVT_EXPERIMENT_END = wx.PyEventBinder(wx.NewEventType())

class ExperimentEvent(wx.PyEvent):
    _COCKPIT_TO_WX_TYPE = {
        cockpit.events.PREPARE_FOR_EXPERIMENT : EVT_EXPERIMENT_START,
        cockpit.events.UPDATE_STATUS_LIGHT : EVT_EXPERIMENT_STEP,
        cockpit.events.CLEANUP_AFTER_EXPERIMENT : EVT_EXPERIMENT_CLEANUP,
        cockpit.events.EXPERIMENT_COMPLETE : EVT_EXPERIMENT_END,
    }
    def __init__(self, cockpit_event_type):
        super(ExperimentEvent, self).__init__()
        wx_event_type = self._COCKPIT_TO_WX_TYPE[cockpit_event_type]
        self.SetEventType(wx_event_type.typeId)


class ExperimentEvtEmitter(cockpit.gui.EvtEmitter):
    """Emits :class:`ExperimentEvent` for a specific experiment.

    Given any specific experiment related event, we don't know to what
    experiment it pertains to.  This class provides that.

    TODO: fix the too verbose names in this class and duplication.
    """

    def __init__(self, parent, experiment):
        super(ExperimentEvtEmitter, self).__init__(parent)
        self._experiment = experiment

        self._cockpit_events_to_subscription_functions = {
            cockpit.events.UPDATE_STATUS_LIGHT : self._OnUpdateStatusLight,
            cockpit.events.CLEANUP_AFTER_EXPERIMENT : self._OnCleanupAfterExperiment,
            cockpit.events.EXPERIMENT_COMPLETE : self._OnExperimentCompletion,
        }
        cockpit.events.subscribe(cockpit.events.PREPARE_FOR_EXPERIMENT,
                                 self._OnExperimentPreparation)

    def _OnExperimentPreparation(self, experiment):
        ## Given any specific experiment related event, we don't know
        ## to what experiment it pertains to.  Assuming that only one
        ## experiment can be running at any time, we wait until the
        ## experiment starts and subscribe to the events.  When the
        ## experiment ends, we unsubscribe.
        if experiment == self._experiment:
            for cockpit_event_type, function in self._cockpit_events_to_subscription_functions.items():
                cockpit.events.subscribe(cockpit_event_type, function)

    def _OnUpdateStatusLight(self, light_name, text, rgb):
        ## XXX: ugly hack.  We still have the status light window.
        ## Currently, the data saver is sending this event with light
        ## name 'image count' and empty text to clear the window text
        ## when the experiment is done.  This may even happen after
        ## the experiment has been completed.  Skip that one.  Maybe
        ## later, we get experiment to emit nicer events instead of
        ## events meant to the light window only.
        if light_name == 'image count' and text == '':
            return
        self._EmitExperimentEvent(cockpit.events.UPDATE_STATUS_LIGHT)

    def _OnCleanupAfterExperiment(self):
        self._EmitExperimentEvent(cockpit.events.CLEANUP_AFTER_EXPERIMENT)

    def _OnExperimentCompletion(self):
        self._EmitExperimentEvent(cockpit.events.EXPERIMENT_COMPLETE)
        for cockpit_event_type, function in self._cockpit_events_to_subscription_functions.items():
            cockpit.events.unsubscribe(cockpit_event_type, function)

    def _EmitExperimentEvent(self, cockpit_event_type):
        self.AddPendingEvent(ExperimentEvent(cockpit_event_type))


if __name__ == "__main__":
    app = wx.App()
    frame = ExperimentFrame(None)

    # import wx.lib.inspection
    # wx.lib.inspection.InspectionTool().Show()
    cockpit.interfaces.stageMover.initialize()
    frame.Show()
    app.MainLoop()
