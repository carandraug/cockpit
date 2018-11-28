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

import cockpit.experiment


class TestComputingZPositions(unittest.TestCase):
    def assertPositionsEqual(self, start, height, step, expected):
        positions = cockpit.experiment.compute_z_positions(start, height, step)
        self.assertListEqual(positions, expected)

    def test_basic(self):
        self.assertPositionsEqual(3.0, 1.0, 1.0, [3.0, 4.0])
        self.assertPositionsEqual(3.0, 1.0, 0.5, [3.0, 3.5, 4.0])

    def test_with_integers(self):
        self.assertPositionsEqual(3, 1, 1, [3.0, 4.0])

    def test_precision(self):
        ## This will fail if we use numpy.arange to compute the z
        ## positions because of accumulated floating point errors.
        self.assertPositionsEqual(3.0, 1.0, 0.2, [3.0, 3.2, 3.4, 3.6, 3.8, 4.0])

    def test_positions_outside_total_height(self):
        self.assertPositionsEqual(3.0, 5.0, 2.0, [3.0, 5.0, 7.0, 9.0])

    def test_negative_start(self):
        self.assertPositionsEqual(-1.0, 3.0, 1.0, [-1.0, 0.0, 1.0, 2.0])

    def test_negative_step(self):
        self.assertPositionsEqual(3.0, 5.0, -2.0, [3.0, 1.0, -1.0, -3.0])

    def test_negative_stack_height(self):
        with self.assertRaisesRegex(ValueError,
                                    "'stack_height' must be non-negative"):
            cockpit.experiment.compute_z_positions(0.0, -1.0, 1.0)

    def test_zero_step_size(self):
        with self.assertRaisesRegex(ValueError, "'step' must be non-zero"):
            cockpit.experiment.compute_z_positions(0.0, 1.0, 0.0)

    def test_zero_stack_height(self):
        self.assertPositionsEqual(1.0, 0.0, 0.0, [1.0])
        self.assertPositionsEqual(1.0, 0.0, 0.2, [1.0])


class TestExposureSettings(unittest.TestCase):
    def test_get_longest(self):
        a = cockpit.experiment.ExposureSettings()
        a.add_light('a', 10)
        a.add_light('b', 15)
        a.add_light('c', 5)
        self.assertEqual(a.longest_exposure(), 15)

    def test_get_longest_empty(self):
        a = cockpit.experiment.ExposureSettings()
        self.assertEqual(a.longest_exposure(), 0.0)


class TestExposureSettingsSequences(unittest.TestCase):
    def setUp(self):
        self.cls = cockpit.experiment.ExposureSettings

        ## More cameras than lights
        self.a = cockpit.experiment.ExposureSettings()
        self.a.add_camera('cam1')
        self.a.add_camera('cam2')
        self.a.add_light('light1', 10)

        ## More lights than cameras
        self.b = cockpit.experiment.ExposureSettings()
        self.b.add_camera('cam2')
        self.b.add_camera('cam3')
        self.b.add_light('light1', 0) # light with zero exposure time
        self.b.add_light('light2', 5)
        self.b.add_light('light3', 7)

        ## No lights at all, just camera
        self.c = cockpit.experiment.ExposureSettings()
        self.c.add_camera('cam4')

    def test_get_all_from_sequence(self):
        sequence = [self.a, self.b, self.c]
        self.assertSetEqual(self.cls.all_cameras(sequence),
                            {'cam1', 'cam2', 'cam3', 'cam4'})
        self.assertSetEqual(self.cls.all_lights(sequence),
                            {'light1', 'light2', 'light3'})

    def test_empty_sequences(self):
        self.assertSetEqual(self.cls.all_cameras([]), set())
        self.assertSetEqual(self.cls.all_lights([]), set())

    def test_sequences_no_exposures(self):
        empty1 = cockpit.experiment.ExposureSettings()
        empty2 = cockpit.experiment.ExposureSettings()
        sequence = [empty1, empty2]
        self.assertSetEqual(self.cls.all_cameras(sequence), set())
        self.assertSetEqual(self.cls.all_lights(sequence), set())


if __name__ == '__main__':
    unittest.main()
