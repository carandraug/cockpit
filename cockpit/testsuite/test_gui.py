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

import unittest

import cockpit.gui.experiment

import wx


class AutoCloseModalDialog(wx.ModalDialogHook):
    def __init__(self, close_id):
        super().__init__()
        self._close_id = close_id

    def Enter(self, dialog):
        return self._close_id


class WxTestCase(unittest.TestCase):
    def setUp(self):
        self.app = wx.App()

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
        self.modal_hook = AutoCloseModalDialog(wx.ID_OK)
        self.modal_hook.Register()
        self.frame.experiment = self.Experiment(running=True)
        self.frame.Close()
        self.assertFalse(self.app.IsScheduledForDestruction(self.frame))

    def test_closing(self):
        self.frame.experiment = self.Experiment(running=False)
        self.frame.Close()
        self.assertTrue(self.app.IsScheduledForDestruction(self.frame))


if __name__ == '__main__':
    unittest.main()
