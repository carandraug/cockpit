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

#import contextlib
import enum
import tempfile
import unittest
import unittest.mock

import cockpit.events
import cockpit.gui.experiment

import wx


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

    def Enter(self, dialog):
        ## Returning ID_NONE does nothing.
        if self.close_id is not wx.ID_NONE:
            self.counter += 1
        return self.close_id

    def __enter__(self):
        self.Register()
        return self

    def __exit__(self, xc_type, exc_value, traceback):
        self.Unregister()

def find_button(window, label):
    """Find a button by its label.

    Looking for a button by using its label ensures that we really
    click on the button that has a specific text.
    """
    for child in window.GetChildren():
        if child.ClassName == 'wxButton' and child.LabelText == label:
            return child
    raise RuntimeError("failed to find '%s' button in ctrl" % label)


def click_button(button):
    click = wx.CommandEvent(wx.wxEVT_COMMAND_BUTTON_CLICKED, button.Id)
    button.ProcessEvent(click)


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

    def setup_clicks(self, labels):
        """Add click_ attributes that mimick clicking on buttons.

        The new attributes are callable which take as argument the
        window where to look for the button.
        """
        def click_factory(label):
            return lambda ctrl : click_button(find_button(ctrl, label))

        for label in labels:
            attr_name = 'click_' + label.lower().replace(' ', '_')
            setattr(self, attr_name, click_factory(label))


class TestEnumChoice(WxTestCase):
    class TestEnum(enum.Enum):
        A = 'a'
        B = 'b'
        C = 'c'

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

    def test_prevent_close(self):
        with AutoCloseModalDialog(wx.ID_OK) as auto_ok:
            self.frame.experiment = self.Experiment(running=True)
            self.frame.Close()
            self.assertEqual(auto_ok.counter, 1)
            self.assertFalse(self.app.IsScheduledForDestruction(self.frame))

    def test_closing(self):
        self.frame.experiment = self.Experiment(running=False)
        self.frame.Close()
        self.assertTrue(self.app.IsScheduledForDestruction(self.frame))

    def test_file_overwrite_dialog(self):
        tfile = tempfile.NamedTemporaryFile()
        with AutoCloseModalDialog(wx.ID_NO) as auto_no:
            self.assertFalse(self.frame.CheckFileOverwrite(tfile.name))
            self.assertEqual(auto_no.counter, 1)

        with  AutoCloseModalDialog(wx.ID_YES) as auto_yes:
            self.assertTrue(self.frame.CheckFileOverwrite(tfile.name))
            self.assertEqual(auto_yes.counter, 1)

    def test_dir_overwrite_dialog(self):
        counter = 0
        with tempfile.TemporaryDirectory() as dirpath:
            ## Whatever happens, in whatever way the dialog is
            ## discarded, we never overwrite a directory.
            for close_id in (wx.ID_OK, wx.ID_CANCEL, wx.ID_NO, wx.ID_YES):
                with AutoCloseModalDialog(close_id) as auto_close:
                    self.assertFalse(self.frame.CheckFileOverwrite(dirpath))
                    self.assertEqual(auto_close.counter, 1)

    def test_abort_experiment(self):
        self.frame.OnExperimentStart()
        self.frame.experiment = TestExperimentFrame.Experiment(running=True)
        click_evt = wx.CommandEvent(wx.wxEVT_COMMAND_BUTTON_CLICKED)

        with AutoCloseModalDialog(wx.ID_CANCEL) as auto_cancel:
            self.frame._abort.ProcessEvent(click_evt)
            self.assertEqual(auto_cancel.counter, 1)
        self.assertFalse(self.frame._book.IsEnabled())

        self.abort_event_published = False
        def check_publication():
            self.abort_event_published = True
        cockpit.events.subscribe(cockpit.events.USER_ABORT,
                                 check_publication)
        with AutoCloseModalDialog(wx.ID_YES) as auto_yes:
            self.frame._abort.ProcessEvent(click_evt)
            self.assertEqual(auto_yes.counter, 1)
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



class TestSitesRearrange(WxTestCase):
    def setUp(self):
        super().setUp()
        self.frame = wx.Frame(None)

    @staticmethod
    def get_n_sites(n):
        from cockpit.interfaces.stageMover import Site
        return tuple([Site(None) for i in range(n)])

class TestSitesRearrangeList(TestSitesRearrange):
    def setUp(self):
        super().setUp()
        def list_factory(order, sites):
            from cockpit.gui.experiment import SitesRearrangeList
            return SitesRearrangeList(self.frame, order=order, sites=sites)
        self.list_factory = list_factory

    def test_empty(self):
        slist = self.list_factory([], [])
        self.assertTupleEqual(slist.Sites, tuple())
        self.assertTupleEqual(slist.CheckedSites, tuple())

    def test_get_all(self):
        sites = self.get_n_sites(4)

        slist = self.list_factory([0,1,2,3], sites)
        self.assertTupleEqual(slist.Sites, sites)

        slist = self.list_factory([-1,-2,-3,-4], sites)
        self.assertTupleEqual(slist.Sites, sites)

    def test_get_checked(self):
        sites = self.get_n_sites(4)

        slist = self.list_factory([0, 1, 2, 3], sites)
        self.assertTupleEqual(slist.CheckedSites, sites)

        slist = self.list_factory([-1,-2,-3,-4], sites)
        self.assertTupleEqual(slist.CheckedSites, tuple())

        slist = self.list_factory([0,-2,2,-4], sites)
        self.assertTupleEqual(slist.CheckedSites, (sites[0], sites[2]))

    def test_sites_order(self):
        sites = self.get_n_sites(4)
        reordered = lambda order: tuple([sites[i] for i in order])
        slist = self.list_factory([0, 1, 2, 3], sites)

        slist.Selection = 2
        slist.MoveCurrentUp()
        self.assertTupleEqual(slist.Sites, reordered([0,2,1,3]))
        slist.MoveCurrentUp()
        self.assertTupleEqual(slist.Sites, reordered([2,0,1,3]))
        slist.Check(0, False)
        self.assertTupleEqual(slist.Sites, reordered([2,0,1,3]))
        slist.Selection = 1
        slist.MoveCurrentDown()
        self.assertTupleEqual(slist.Sites, reordered([2,1,0,3]))
        slist.Check(2, False)
        self.assertTupleEqual(slist.Sites, reordered([2,1,0,3]))


class TestSitesRearrangeCtrl(TestSitesRearrange):
    def setUp(self):
        super().setUp()
        def ctrl_factory(order, sites):
            from cockpit.gui.experiment import SitesRearrangeCtrl
            return SitesRearrangeCtrl(self.frame, order=order, sites=sites)
        self.ctrl_factory = ctrl_factory

        self.setup_clicks(['Up', 'Down', 'Select All', 'Deselect All',
                           'Optimise'])

    def test_check_uncheck_on_constructor(self):
        sites = self.get_n_sites(4)
        ctrl = self.ctrl_factory([0,1,2,3], sites)
        self.assertTupleEqual(ctrl.List.CheckedSites, sites)
        ctrl = self.ctrl_factory([-1,-2,-3,-4], sites)
        self.assertTupleEqual(ctrl.List.CheckedSites, tuple())
        ctrl = self.ctrl_factory([-1,-2,2,-4], sites)
        self.assertTupleEqual(ctrl.List.CheckedSites, (sites[2],))

    def test_change_all(self):
        sites = self.get_n_sites(4)
        ctrl = self.ctrl_factory([0,1,2,3], sites)

        self.click_select_all(ctrl)
        self.assertTupleEqual(ctrl.List.CheckedSites, sites)
        self.click_deselect_all(ctrl)
        self.assertTupleEqual(ctrl.List.CheckedSites, tuple())
        self.click_select_all(ctrl)
        self.assertTupleEqual(ctrl.List.CheckedSites, sites)

    def test_empty(self):
        ctrl = self.ctrl_factory([], [])
        def assert_all_empty():
            self.assertTupleEqual(ctrl.List.Sites, tuple())
            self.assertTupleEqual(ctrl.List.CheckedSites, tuple())

        assert_all_empty()
        self.click_select_all(ctrl)
        assert_all_empty()
        self.click_deselect_all(ctrl)
        assert_all_empty()
        self.click_select_all(ctrl)
        assert_all_empty()

    def test_moving_up_and_down(self):
        sites = self.get_n_sites(4)
        reordered = lambda order: tuple([sites[i] for i in order])
        ctrl = self.ctrl_factory([0,1,2,3], sites)

        ctrl.List.Selection = 2
        self.click_up(ctrl)
        self.assertTupleEqual(ctrl.List.Sites, reordered([0, 2, 1, 3]))
        self.click_up(ctrl)
        self.assertTupleEqual(ctrl.List.Sites, reordered([2, 0, 1, 3]))
        self.click_down(ctrl)
        self.assertTupleEqual(ctrl.List.Sites, reordered([0, 2, 1, 3]))

        ## Nothing breaks when we press up/down and there's nothing
        ## selected.
        ctrl.List.Selection = -1
        self.click_up(ctrl)
        self.click_down(ctrl)
        self.click_down(ctrl)
        self.assertTupleEqual(ctrl.List.Sites, reordered([0, 2, 1, 3]))

    def test_moving_outside_of_boundaries(self):
        sites = self.get_n_sites(4)
        ctrl = self.ctrl_factory([0,1,2,3], sites)

        ctrl.List.Selection = 0
        self.click_up(ctrl)
        self.assertTupleEqual(ctrl.List.Sites, sites)
        ctrl.List.Selection = 3
        self.click_down(ctrl)
        self.assertTupleEqual(ctrl.List.Sites, sites)

    ## At the moment, it's too much work to mock the whole thing
    ## enough that we can actually call optimise, so just replace
    ## it with reverse.
    @unittest.mock.patch('cockpit.interfaces.stageMover.optimisedSiteOrder',
                         lambda x : list(reversed(x)))
    def test_optimise(self):
        sites = self.get_n_sites(4)
        ctrl = self.ctrl_factory([0,1,2,3], sites)

        reordered = lambda order: tuple([sites[i] for i in order])

        self.click_optimise(ctrl)
        self.assertTupleEqual(ctrl.List.Sites, reordered([3,2,1,0]))
        self.click_optimise(ctrl)
        self.assertTupleEqual(ctrl.List.Sites, reordered([0,1,2,3]))

        ctrl.List.Check(3, False)
        self.click_optimise(ctrl)
        self.assertTupleEqual(ctrl.List.Sites, reordered([2,1,0,3]))
        ctrl.List.Check(3, True)
        ctrl.List.Check(1, False)
        self.click_optimise(ctrl)
        self.assertTupleEqual(ctrl.List.Sites, reordered([3,0,2,1]))
        ## With two unchecked
        ctrl.List.Check(0, False)
        self.click_optimise(ctrl)
        self.assertTupleEqual(ctrl.List.Sites, reordered([2,0,3,1]))
        ## With all unchecked
        ctrl.List.CheckAll(False)
        self.click_optimise(ctrl)
        self.assertTupleEqual(ctrl.List.Sites, reordered([2,0,3,1]))


class TestSitesRearrangeDialog(TestSitesRearrange):
    def setUp(self):
        super().setUp()
        def dlg_factory(order, sites):
            from cockpit.gui.experiment import SitesRearrangeDialog
            return SitesRearrangeDialog(self.frame, message='',
                                        order=order, sites=sites)
        self.dlg_factory = dlg_factory

    def test_constructor(self):
        dlg = self.dlg_factory([], [])
        with AutoCloseModalDialog(wx.ID_OK) as auto_ok:
            dlg.ShowModal()
            self.assertEqual(auto_ok.counter, 1)
        self.assertTupleEqual(dlg.List.Sites, tuple())

        sites = self.get_n_sites(2)
        dlg = self.dlg_factory([0,1], sites)
        with AutoCloseModalDialog(wx.ID_OK) as auto_ok:
            dlg.ShowModal()
            self.assertEqual(auto_ok.counter, 1)
        self.assertTupleEqual(dlg.List.Sites, sites)


class TestMultiSiteSettings(WxTestCase):
    ## Convenience actions to use by the AutoCloseModalDialog
    @staticmethod
    def select_all(dialog):
        click_button(find_button(dialog._ctrl, 'Select All'))
    @staticmethod
    def deselect_all(dialog):
        click_button(find_button(dialog._ctrl, 'Deselect All'))

    def setUp(self):
        super().setUp()

        cockpit.interfaces.stageMover.initialize()
        for site in cockpit.interfaces.stageMover.getAllSites():
            cockpit.interfaces.stageMover.deleteSite(site)

        for i in range(4):
            cockpit.interfaces.stageMover.saveSite()

        self.panel = cockpit.gui.experiment.MultiSiteSettingsPanel(self.frame)
        self.setup_clicks(['Change Selection'])

    # def test_select_dialog(self):
    #     ## XXX: should we have a property to get/set this value?
    #     self.assertEqual(self.panel._selected_text.Value, '')
    #     with AutoCloseModalDialog(wx.ID_OK) as auto_ok:
    #         self.click_change_selection(self.panel)
    #     self.assertEqual(self.panel._selected_text.Value, '')

    def test_cancel_dialog(self):
        class SelectAllThenClose(AutoCloseModalDialog):
            def Enter(self, dialog):
                TestMultiSiteSettings.select_all(dialog)
                return super().Enter(dialog)
            #     click_button(find_button(dialog._ctrl, 'Select All'))
            # return super().Enter(dialog)

        with SelectAllThenClose(wx.ID_OK) as auto_ok:
            self.click_change_selection(self.panel)
            self.assertRegex(self.panel._selected_text.Value,
                             '^\d+, \d+, \d+, \d+$')
            pass

if __name__ == '__main__':
    unittest.main()
