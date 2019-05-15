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
import unittest.mock

import wx

import cockpit.events
import cockpit.gui


class AutoCloseModalDialog(wx.ModalDialogHook):
    """Immediately close the dialog using the given ID.

    Also, keeps a counter of how many times it was used.  Supports
    usage via the with context statement::

        with AutoCloseModalDialog(wx.ID_OK) as auto_ok:
            ...

    """
    def __init__(self, close_id):
        super().__init__()
        self.close_id = close_id
        self.counter = 0
        self.actions = []

    def Enter(self, dialog):
        for action in self.actions:
            action(dialog)

        ## Returning ID_NONE does nothing.
        if self.close_id is not wx.ID_NONE:
            self.counter += 1
        return self.close_id

    def __enter__(self):
        self.Register()
        return self

    def __exit__(self, xc_type, exc_value, traceback):
        self.Unregister()


class WxTestCase(unittest.TestCase):
    def setUp(self):
        self.app = wx.App()
        self.frame = wx.Frame(None)

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


class TestCockpitEvents(WxTestCase):
    def setUp(self):
        super().setUp()
        self.mock_function = unittest.mock.Mock()

    def create_and_bind(self, window):
        emitter = cockpit.gui.EvtEmitter(window, 'test gui')
        emitter.Bind(cockpit.gui.EVT_COCKPIT, self.mock_function)

    def trigger_event(self):
        cockpit.events.publish('test gui')
        self.app.ProcessPendingEvents()

    def test_bind(self):
        self.create_and_bind(self.frame)
        self.trigger_event()
        self.mock_function.assert_called_once()

    def test_parent_destroy(self):
        window = wx.Frame(self.frame)
        self.create_and_bind(window)
        window.ProcessEvent(wx.CommandEvent(wx.wxEVT_DESTROY))
        self.trigger_event()
        self.mock_function.assert_not_called()


class TestExceptionBox(WxTestCase):
    def test_fails_if_not_handling_exception(self):
        with self.assertRaisesRegex(RuntimeError, 'Not handling an exception'):
            cockpit.gui.ExceptionBox()

    def test_it_runs(self):
        """ExceptionBox does not raise an exception.

        This is a tricky one to test and there isn't much to test.  We
        just need to make sure that it doesn't fail itself.
        """
        with AutoCloseModalDialog(wx.ID_OK) as auto_ok:
            try:
                raise Exception('test exception for ExceptionBox()')
            except Exception:
                cockpit.gui.ExceptionBox()


if __name__ == '__main__':
    unittest.main()
