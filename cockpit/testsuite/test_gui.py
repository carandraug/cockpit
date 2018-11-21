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

import contextlib
import enum
import tempfile
import unittest
import unittest.mock

import wx

import cockpit.events
import cockpit.events
import cockpit.gui
import cockpit.gui.experiment

from cockpit.interfaces import stageMover


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

    @contextlib.contextmanager
    def mocked_saved_top_bottom(self, top, bottom):
        import cockpit.gui.saveTopBottomPanel as savePosPanel
        with unittest.mock.patch.object(savePosPanel, 'savedTop', top) as a, \
             unittest.mock.patch.object(savePosPanel, 'savedBottom', bottom) as b:
            yield (a, b)

    def mocked_current_z_position(self, position):
        def mocked_position_for_axis(axis):
            if axis != 2:
                raise RuntimeError('mock is only prepared to return z')
            return position
        return unittest.mock.patch('cockpit.interfaces.stageMover.getPositionForAxis',
                                   new=mocked_position_for_axis)

    def change_position(self, selection):
        self.panel._position.EnumSelection = selection
        choice_evt = wx.CommandEvent(wx.wxEVT_COMMAND_CHOICE_SELECTED)
        self.panel._position.ProcessEvent(choice_evt)

    def change_value(self, control, value):
        evt = wx.CommandEvent(wx.wxEVT_KILL_FOCUS)
        control.Value = value
        control.ProcessEvent(evt)

    def test_using_saved_z(self):
        with self.mocked_saved_top_bottom(50, 40):
            self.assertTrue(self.panel._stack_height.IsEnabled())

            self.change_position(self.panel.Position.SAVED)
            self.assertEqual(self.panel.StackHeight, 10.0)
            self.assertFalse(self.panel._stack_height.IsEnabled())

            self.change_position(self.panel.Position.CENTER)
            self.assertTrue(self.panel._stack_height.IsEnabled())

    def test_number_slices_display(self):
        with self.mocked_current_z_position(10):
            self.change_value(self.panel._stack_height, '1')
            self.change_value(self.panel._step_size, '0.5')

            self.assertEqual(self.panel._number_slices.Value, '3')

            self.change_value(self.panel._step_size, '1')
            self.assertEqual(self.panel._number_slices.Value, '2')

            self.change_value(self.panel._step_size, '1.1')
            self.assertEqual(self.panel._number_slices.Value, '2')

            self.change_value(self.panel._stack_height, '2.5')
            self.assertEqual(self.panel._number_slices.Value, '4')


class TestSitesRearrange(WxTestCase):
    """Base class for the tests of the whole SitesRearrange stuff.
    """
    def setUp(self):
        super().setUp()
        self.frame = wx.Frame(None)

    @staticmethod
    def get_n_sites(n):
        return [stageMover.Site(None) for i in range(n)]

    def assertSitesOrder(self, sites, all_sites, order, msg=None):
        self.assertListEqual(sites, [all_sites[i] for i in order], msg)


class TestSitesRearrangeList(TestSitesRearrange):
    def setUp(self):
        super().setUp()
        def list_factory(order, sites):
            from cockpit.gui.experiment import SitesRearrangeList
            return SitesRearrangeList(self.frame, order=order, sites=sites)
        self.list_factory = list_factory

    def test_getters(self):
        sites = self.get_n_sites(4)
        def do_asserts(init_order, sites_order, checked_order):
            slist = self.list_factory(init_order, sites)
            self.assertSitesOrder(slist.Sites, sites, sites_order)
            self.assertSitesOrder(slist.CheckedSites, sites, checked_order)

        do_asserts([0, 1, 2, 3], [0, 1, 2, 3], [0, 1, 2, 3])
        do_asserts([-1, -2, -3, -4], [0, 1, 2, 3], [])
        do_asserts([0, -2, 2, -4], [0, 1, 2, 3], [0, 2])
        do_asserts([0, 1, 1, 1], [0, 1, 1, 1], [0, 1, 1, 1])
        do_asserts([0, 1, -2, 2], [0, 1, 1, 2], [0, 1, 2])
        do_asserts([3, -2, -2, 3], [3, 1, 1, 3], [3, 3])

    def test_empty(self):
        slist = self.list_factory([], [])
        self.assertListEqual(slist.Sites, [])
        self.assertListEqual(slist.CheckedSites, [])

    def test_moving(self):
        sites = self.get_n_sites(4)
        slist = self.list_factory([0, 1, 2, 3], sites)
        def do_asserts(sites_order, checked_order):
            self.assertSitesOrder(slist.Sites, sites, sites_order)
            self.assertSitesOrder(slist.CheckedSites, sites, checked_order)

        slist.Selection = 2
        slist.MoveCurrentUp()
        do_asserts([0, 2, 1, 3], [0, 2, 1, 3])

        slist.MoveCurrentUp()
        do_asserts([2, 0, 1, 3], [2, 0, 1, 3])

        slist.Check(0, False)
        do_asserts([2, 0, 1, 3], [0, 1, 3])

        slist.Selection = 1
        slist.MoveCurrentDown()
        do_asserts([2, 1, 0, 3], [1, 0, 3])

        slist.Check(2, False)
        do_asserts([2, 1, 0, 3], [1, 3])


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
        def do_asserts(init_order, sites_order, checked_order):
            ctrl = self.ctrl_factory(init_order, sites)
            self.assertSitesOrder(ctrl.List.Sites, sites, sites_order)
            self.assertSitesOrder(ctrl.List.CheckedSites, sites, checked_order)

        do_asserts([0, 1, 2, 3], [0, 1, 2, 3], [0, 1, 2, 3])
        do_asserts([-1, -2, -3, -4], [0, 1, 2, 3], [])
        do_asserts([-1, -2, 2, -4], [0, 1, 2, 3], [2])

    def test_change_all(self):
        sites = self.get_n_sites(4)
        ctrl = self.ctrl_factory([0,1,2,3], sites)

        self.click_select_all(ctrl)
        self.assertListEqual(ctrl.List.CheckedSites, sites)
        self.click_deselect_all(ctrl)
        self.assertListEqual(ctrl.List.CheckedSites, [])
        self.click_select_all(ctrl)
        self.assertListEqual(ctrl.List.CheckedSites, sites)

    def test_empty(self):
        ctrl = self.ctrl_factory([], [])
        def assert_all_empty():
            self.assertListEqual(ctrl.List.Sites, [])
            self.assertListEqual(ctrl.List.CheckedSites, [])

        assert_all_empty()
        self.click_select_all(ctrl)
        assert_all_empty()
        self.click_deselect_all(ctrl)
        assert_all_empty()
        self.click_select_all(ctrl)
        assert_all_empty()

    def test_moving_up_and_down(self):
        sites = self.get_n_sites(4)
        ctrl = self.ctrl_factory([0,1,2,3], sites)

        ctrl.List.Selection = 2
        for action, order in ((self.click_up, [0, 2, 1, 3]),
                              (self.click_up, [2, 0, 1, 3]),
                              (self.click_down, [0, 2, 1, 3])):
            action(ctrl)
            self.assertSitesOrder(ctrl.List.Sites, sites, order)

        ctrl.List.Selection = -1 # select nothing
        self.click_up(ctrl)
        self.click_down(ctrl)
        self.click_down(ctrl)
        self.assertSitesOrder(ctrl.List.Sites, sites, [0, 2, 1, 3])

    def test_moving_outside_of_boundaries(self):
        sites = self.get_n_sites(4)
        ctrl = self.ctrl_factory([0,1,2,3], sites)

        ctrl.List.Selection = 0
        self.click_up(ctrl)
        self.assertListEqual(ctrl.List.Sites, sites)
        ctrl.List.Selection = 3
        self.click_down(ctrl)
        self.assertListEqual(ctrl.List.Sites, sites)

    ## At the moment, it's too much work to mock the whole thing
    ## enough that we can actually call optimise, so just replace it
    ## with reverse.
    @unittest.mock.patch('cockpit.interfaces.stageMover.optimisedSiteOrder',
                         lambda x : list(reversed(x)))
    def test_optimise(self):
        sites = self.get_n_sites(4)
        ctrl = self.ctrl_factory([0,1,2,3], sites)
        def optimise_then_assert(sites_order, checked_order):
            self.click_optimise(ctrl)
            self.assertSitesOrder(ctrl.List.Sites, sites, sites_order)
            self.assertSitesOrder(ctrl.List.CheckedSites, sites, checked_order)

        optimise_then_assert([3, 2, 1, 0], [3, 2, 1, 0])
        optimise_then_assert([0, 1, 2, 3], [0, 1, 2, 3])

        ctrl.List.Check(3, False)
        optimise_then_assert([2, 1, 0, 3], [2, 1, 0])

        ctrl.List.Check(3, True)
        ctrl.List.Check(1, False)
        optimise_then_assert([3, 0, 2, 1], [3, 0, 2])

        ## With two unchecked
        ctrl.List.Check(0, False)
        optimise_then_assert([2, 0, 3, 1], [2, 0])

        ## With all unchecked
        ctrl.List.CheckAll(False)
        optimise_then_assert([2, 0, 3, 1], [])


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
        self.assertListEqual(dlg.List.Sites, [])

        sites = self.get_n_sites(2)
        dlg = self.dlg_factory([0,1], sites)
        with AutoCloseModalDialog(wx.ID_OK) as auto_ok:
            dlg.ShowModal()
            self.assertEqual(auto_ok.counter, 1)
        self.assertListEqual(dlg.List.Sites, sites)


class TestMultiSiteSettings(WxTestCase):
    ## Convenience actions to use by the AutoCloseModalDialog
    @staticmethod
    def select_all(dialog):
        click_button(find_button(dialog._ctrl, 'Select All'))
    @staticmethod
    def deselect_all(dialog):
        click_button(find_button(dialog._ctrl, 'Deselect All'))
    @staticmethod
    def check_some(dialog, select_index, check=True):
        for i in select_index:
            dialog.List.Check(i, check)

    def setUp(self):
        super().setUp()

        stageMover.initialize()
        for site in stageMover.getAllSites():
            stageMover.deleteSite(site)

        self.sites = [stageMover.saveSite() for i in range(4)]
        self.site_labels = [str(site) for site in self.sites]

        self.panel = cockpit.gui.experiment.MultiSiteSettingsPanel(self.frame)
        self.setup_clicks(['Change Selection'])

    def assertDisplayText(self, text, msg=None):
        self.assertEqual(self.panel._text.Value, text, msg)

    def assertSites(self, sites_indices, msg=None):
        expected_sites = [self.sites[i] for i in sites_indices]
        self.assertListEqual(self.panel.Sites, expected_sites, msg)
        expected_text = ', '.join([str(site) for site in expected_sites])
        self.assertDisplayText(expected_text, msg)

    def doChange(self, change, close_id=wx.ID_OK):
        with AutoCloseModalDialog(close_id) as auto_close:
            auto_close.actions = [change]
            self.click_change_selection(self.panel)

    def test_initial_state(self):
        self.assertEqual(self.panel.Sites, [])
        self.assertDisplayText('')

    def test_sites_setter(self):
        self.panel.Sites = [self.sites[0]]
        self.assertDisplayText(self.site_labels[0])

        self.panel.Sites = [self.sites[0], self.sites[2]]
        self.assertDisplayText(self.site_labels[0] + ', ' + self.site_labels[2])

        self.panel.Sites = self.sites
        self.assertDisplayText(', '.join(self.site_labels))

    def test_select_dialog(self):
        for close_id in [wx.ID_OK, wx.ID_CANCEL]:
            self.doChange(lambda x: None, close_id)
            self.assertSites([])

    def test_selecting_in_dialog(self):
        self.doChange(self.select_all)
        self.assertSites([0, 1, 2, 3])

        self.doChange(lambda x: None, wx.ID_CANCEL)
        self.assertSites([0, 1, 2, 3])

        self.doChange(self.deselect_all, wx.ID_CANCEL)
        self.assertSites([0, 1, 2, 3])

        self.doChange(self.deselect_all)
        self.assertSites([])

    def test_selecting_some_in_dialog(self):
        self.doChange(lambda dialog: self.check_some(dialog, [0, 1, 3]))
        self.assertSites([0, 1, 3])

        self.doChange(lambda dialog: self.check_some(dialog, [1], False))
        self.assertSites([0, 3])

        self.doChange(lambda dialog: self.check_some(dialog, [2]))
        self.assertSites([0, 3, 1])

    def test_deleting_sites(self):
        self.doChange(lambda dialog: self.check_some(dialog, [0, 1, 3]))
        self.assertSites([0, 1, 3])

        stageMover.deleteSite(self.sites[1].uniqueID)
        self.assertSites([0, 3])
        stageMover.deleteSite(self.sites[2].uniqueID)
        self.assertSites([0, 3])


if __name__ == '__main__':
    unittest.main()
