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

import enum
import tempfile
import unittest

import cockpit.events
import cockpit.gui.experiment

import wx


class AutoCloseModalDialog(wx.ModalDialogHook):
    def __init__(self):
        super().__init__()
        self.close_id = None
        self.counter = 0

    def Enter(self, dialog):
        if self.close_id is not None:
            self.counter += 1
            return self.close_id
        else:
            return wx.ID_NONE


class WxTestCase(unittest.TestCase):
    def setUp(self):
        self.app = wx.App()
        self.modal_hook = AutoCloseModalDialog()
        self.modal_hook.Register()

    def tearDown(self):
        def cleanup():
            for tlw in wx.GetTopLevelWindows():
                if tlw:
                    if isinstance(tlw, wx.Dialog) and tlw.IsModal():
                        tlw.EndModal(0)
                    else:
                        tlw.Close(force=True)
                    wx.CallAfter(tlw.Destroy)
            wx.WakeUpIdle()

        wx.CallLater(100, cleanup)
        self.app.MainLoop()
        del self.app


class TestEnumChoice(WxTestCase):
    class TestEnum(enum.Enum):
        A = 'a'
        B = 'b'
        C = 'c'

    def setUp(self):
        super().setUp()
        self.frame = wx.Frame(None)
        self.frame.Show()

    def test_basic(self):
        c = cockpit.gui.experiment.EnumChoice(self.frame, choices=self.TestEnum,
                                              default=self.TestEnum.B)
        self.assertTrue(c.Count == 3)
        self.assertTrue(c.EnumSelection == self.TestEnum.B)
        self.assertTrue(c.Selection == 1)

    def test_fail_on_missing_default(self):
        class OtherEnum(enum.Enum):
            A = 'a'
        with self.assertRaises(TypeError):
            c = cockpit.gui.experiment.EnumChoice(self.frame,
                                                  choices=self.TestEnum,
                                                  default=OtherEnum.A)

    def test_fail_on_non_unique_enum(self):
        class NonUniqueEnum(enum.Enum):
            A = 'a'
            B = 'b'
            C = 'a'
        with self.assertRaises(ValueError):
            c = cockpit.gui.experiment.EnumChoice(self.frame,
                                                  choices=NonUniqueEnum,
                                                  default=NonUniqueEnum.A)

    def test_set_selection(self):
        c = cockpit.gui.experiment.EnumChoice(self.frame, choices=self.TestEnum,
                                              default=self.TestEnum.B)
        c.EnumSelection = self.TestEnum.C
        self.assertTrue(c.EnumSelection == self.TestEnum.C)


class TestExperimentFrame(WxTestCase):

    class Experiment:
        def __init__(self, running):
            self.running = running

        def is_running(self):
            return self.running

    def setUp(self):
        super().setUp()
        self.frame = cockpit.gui.experiment.ExperimentFrame(None)
        self.frame.Show()
        self.frame.PostSizeEvent()

    def test_prevent_close(self):
        self.frame.experiment = TestExperimentFrame.Experiment(running=True)
        self.modal_hook.close_id = wx.ID_OK
        self.frame.Close()
        self.assertEqual(self.modal_hook.counter, 1)
        self.assertFalse(self.app.IsScheduledForDestruction(self.frame))

    def test_closing(self):
        self.frame.experiment = self.Experiment(running=False)
        self.frame.Close()
        self.assertEqual(self.modal_hook.counter, 0)
        self.assertTrue(self.app.IsScheduledForDestruction(self.frame))

    def test_file_overwrite_dialog(self):
        tfile = tempfile.NamedTemporaryFile()
        self.modal_hook.close_id = wx.ID_NO
        self.assertFalse(self.frame.CheckFileOverwrite(tfile.name))
        self.assertEqual(self.modal_hook.counter, 1)
        self.modal_hook.close_id = wx.ID_YES
        self.assertTrue(self.frame.CheckFileOverwrite(tfile.name))
        self.assertEqual(self.modal_hook.counter, 2)

    def test_dir_overwrite_dialog(self):
        counter = 0
        with tempfile.TemporaryDirectory() as dirpath:
            ## Whatever happens, in whatever way the dialog is
            ## discarded, we never overwrite a directory.
            for close_id in (wx.ID_OK, wx.ID_CANCEL, wx.ID_NO, wx.ID_YES):
                self.modal_hook.close_id = close_id
                self.assertFalse(self.frame.CheckFileOverwrite(dirpath))
                counter += 1
                self.assertEqual(self.modal_hook.counter, counter)

    def test_abort_experiment(self):
        self.frame.OnExperimentStart()
        self.frame.experiment = TestExperimentFrame.Experiment(running=True)
        click_evt = wx.CommandEvent(wx.wxEVT_COMMAND_BUTTON_CLICKED)

        self.modal_hook.close_id = wx.ID_CANCEL
        self.frame._abort.ProcessEvent(click_evt)
        self.assertEqual(self.modal_hook.counter, 1)
        self.assertFalse(self.frame._book.IsEnabled())

        self.abort_event_published = False
        def check_publication():
            self.abort_event_published = True

        self.modal_hook.close_id = wx.ID_YES
        cockpit.events.subscribe(cockpit.events.USER_ABORT, check_publication)
        self.frame._abort.ProcessEvent(click_evt)
        self.assertEqual(self.modal_hook.counter, 2)
        self.assertTrue(self.abort_event_published)
        ## ensure that we don't enable runnning another experiment
        ## until experiment finishes all cleanup
        self.assertFalse(self.frame._book.IsEnabled())
        self.assertFalse(self.frame._run.IsEnabled())

        cockpit.events.publish(cockpit.events.EXPERIMENT_COMPLETE)
        self.assertTrue(self.frame._book.IsEnabled())
        self.assertTrue(self.frame._run.IsEnabled())

class TestZSettings(WxTestCase):
    def setUp(self):
        super().setUp()
        self.frame = wx.Frame(None)
        self.panel = cockpit.gui.experiment.ZSettingsPanel(self.frame)

    def test_saved_z(self):
        choice_evt = wx.CommandEvent(wx.wxEVT_COMMAND_CHOICE_SELECTED)

        self.assertTrue(self.panel._stack_height.IsEnabled())
        self.panel._position.EnumSelection = self.panel.Position.SAVED
        self.panel._position.ProcessEvent(choice_evt)
        self.assertFalse(self.panel._stack_height.IsEnabled())
        self.panel._position.EnumSelection = self.panel.Position.CENTER
        self.panel._position.ProcessEvent(choice_evt)
        self.assertTrue(self.panel._stack_height.IsEnabled())



if __name__ == '__main__':
    unittest.main()
