#!/usr/bin/env python
# -*- coding: utf-8 -*-

## Copyright (C) 2021 University of Oxford
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

"""Configuration of cockpit and device depot, via both file and command line.

This module has classes and functions for the configuration of both
the cockpit program and the device depot.  It has the logic for the
default config files and values, and command line options.

"""

import argparse
import configparser
import importlib
import logging
import os
import os.path
import sys
import typing
from pathlib import Path
from typing import List, Type, Union

import Pyro4


_logger = logging.getLogger(__name__)


_PROGRAM_NAME = 'cockpit'


class CockpitConfig(configparser.ConfigParser):
    """Configuration for cockpit.

    Args:
        cmd_line_options: parsed command line options, which controls
            which configuration files are read, and is then merged
            into the configuration itself.

    """
    def __init__(self, cmd_line_options: argparse.Namespace):
        super().__init__(converters=_type_converters)
        self.read_dict(_default_cockpit_config())

        ## Check if depot or config files specified exist (see #710).
        for fpath in cmd_line_options.depot_files:
            if not fpath.is_file() or not os.access(fpath, os.R_OK):
                raise Exception("Unable to read depot file %s" % fpath)
        for fpath in cmd_line_options.config_files:
            if not fpath.is_file() or not os.access(fpath, os.R_OK):
                raise Exception("Unable to read config file %s" % fpath)

        ## Read cockpit config files.  Least "important" files go
        ## first so that later files can override option values.
        if cmd_line_options.read_system_config_files:
            self.read(reversed(default_system_cockpit_config_files()))
        if cmd_line_options.read_user_config_files:
            self.read(reversed(default_user_cockpit_config_files()))
        self.read(cmd_line_options.config_files)

        ## Command line options take precedence over everything, so
        ## adding those to the config is done last.
        self._mixin_cmd_line_options(cmd_line_options)

        self._depot_config = DepotConfig(self['global'].getpaths('depot-files'))

    def _mixin_cmd_line_options(self, options) -> None:
        ## Multiple depot config files behave different from cockpit
        ## config files in that sections with same name are not merged
        ## or overload one another.  We don't because we believe it to
        ## be too error prone.  Similarly, we don't want to try read
        ## default depot files if there's depot files mentioned
        ## anywhere else.
        ## 1. If specified via command line, then read only those.
        ## 2. If defined in any of the cockpit config files, read only those.
        ## 3. Otherwise, read and merge the system and user default.
        if options.depot_files:
            self._set_depot_files(options.depot_files)
        elif self.has_option('global', 'depot-files'):
            pass # Already set in a cockpit config file, so skip.
        else:
            depot_files = []
            if options.read_system_config_files:
                depot_files.extend(default_system_depot_config_files())
            if options.read_user_config_files:
                depot_files.extend(default_user_depot_config_files())
            self._set_depot_files(depot_files)

        if options.debug:
            self.set('log', 'level', 'debug')

    def _set_depot_files(self, depot_files):
        ## FIXME: this is nonsense.  We already have a list of Path
        ## and need to convert them to strings so that configparser
        ## can parse them again.  Maybe we should have our own Config
        ## class and use the ConfigParser class only to parse the ini
        ## files (also, configparser parses the string value each we
        ## access it).
        self.set(
            'global',
            'depot-files',
            '\n'.join([str(f) for f in depot_files])
        )

    @property
    def depot_config(self):
        """Instance of :class:`DepotConfig`.
        """
        return self._depot_config


class DepotConfig(configparser.ConfigParser):
    """Config for a :class:`DeviceDepot`.

    Unlike Python's ``ConfigParser``, it will raise an exception if
    there's multiple devices (sections with same name), even if they
    are in different files.

    Some work in interpreting device config, currently in the
    ``cockpit.depot`` module, may be migrated here with time.

    Args:
        filepaths: list of files with device configurations.

    Raises:
        ``configparser.DuplicateSectionError`` if there's more than
        one device definition on the same or different files.

    """
    def __init__(self, filepaths: List[Path]) -> None:
        super().__init__(converters=_type_converters, interpolation=None)
        self.files = [] # type: List[Path]
        self.read(filepaths)

    def read(self, filenames: List[Path], encoding=None):
        """Read depot configuration files.

        Raises:
            ``configparser.DuplicateSectionError`` if there's more
            than one device definition on the same or different files.
        """
        if isinstance(filenames, (str, bytes, os.PathLike)):
            filenames = [filenames]

        ## The builtin option to avoid duplicated sections (the strict
        ## option) only prevents duplicated sections on the same file.
        ## So we need to do this ourselves (add_section will raise an
        ## exception in case of duplicated sections).
        for filename in filenames:
            file_config = configparser.ConfigParser()
            if file_config.read(filename):
                self.files.append(filename)
                for new_section in file_config.sections():
                    self.add_section(new_section)
                    for k, v in file_config[new_section].items():
                        self[new_section][k] = v

def _default_cockpit_config():
    default = {
        'global' : {
            'channel-files' : '',  # this is parsed as empty list
            'config-dir' : _default_user_config_dir(),
            'data-dir' : _default_user_data_dir(),
            ## The default value of 'depot-files' is only set after
            ## reading the cockpit config files and will also be
            ## dependent on command line options.
#            'depot-files' : '',
            'pyro-pickle-protocol': Pyro4.config.PICKLE_PROTOCOL_VERSION,
        },
        'log' : {
            'level' : 'error',
            'dir' : _default_log_dir(),
            'filename-template' : '%%Y%%m%%d_%%a-%%H%%M.log',
        },
        'stage' : {
            # A list of primitives to draw on the macrostage display.
            'primitives' : '',
            ## TODO: come up with sensible defaults.  These are historical.
            'dishAltitude' : '7570',
            'slideAltitude' : '7370',
            'slideTouchdownAltitude' : '7900',
            ## XXX: these two things are used in the touchscreen code
            ## but they never had a default.
            # 'loadPosition' : '',
            # 'unloadPosition' : '',
        },
        'joystick' : {
            'speed' : 0.01,
        }
    }
    return default


def default_system_cockpit_config_files() -> List[Path]:
    return _default_system_config_files('cockpit.conf')

def default_user_cockpit_config_files() -> List[Path]:
    return _default_user_config_files('cockpit.conf')

def default_system_depot_config_files() -> List[Path]:
    return _default_system_config_files('depot.conf')

def default_user_depot_config_files() -> List[Path]:
    return _default_user_config_files('depot.conf')


def _default_system_config_dirs() -> List[Path]:
    """List of directories, most important first.
    """
    if _is_windows():
        program_data = os.environ.get("ProgramData")
        if program_data:
            base_dirs = [Path(program_data)]
        else:  # Fallback according to KNOWNFOLDERID docs
            _logger.warning("Empty environment variable 'ProgramData'")
            base_dirs = [Path(os.environ["SystemDrive"]) / "ProgramData"]
    elif _is_mac():
        base_dirs = [Path("/Library/Preferences")]
    else:
        ## freedesktop.org Base Directory Specification
        xdg_config_dirs = os.getenv("XDG_CONFIG_DIRS", default="").split(":")
        xdg_config_dirs = [d for d in xdg_config_dirs if d]
        if xdg_config_dirs:
            base_dirs = [Path(d) for d in xdg_config_dirs]
        else:
            base_dirs = [Path("/etc/xdg")]

    return [d / _PROGRAM_NAME for d in base_dirs]

def _default_user_config_dir() -> Path:
    if _is_windows():
        base_dir = Path(os.environ.get("LocalAppData"))
    elif _is_mac():
        base_dir = Path("~/Library/Application Support").expanduser()
    else:
        ## freedesktop.org Base Directory Specification
        xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config_home:
            base_dir = Path(xdg_config_home)
        else:
            base_dir = Path(os.environ["HOME"]) / ".config"
    return base_dir / _PROGRAM_NAME


def _default_user_config_files(fname) -> List[Path]:
    ## In the case of user config, there is always only one directory.
    ## However, for system config case there may be multiple.  Having
    ## *_user_config_* return a string and *_system_config_* return a
    ## list of strings is messy and error prone, so we return a list
    ## even in the case of *_user_config_*.
    return [_default_user_config_dir() / fname]

def _default_system_config_files(fname) -> List[Path]:
    return [d / fname for d in _default_system_config_dirs()]


def _default_log_dir() -> Path:
    if _is_windows():
        local_app_data = os.environ.get("LocalAppData")
        if local_app_data:
            base_dir = Path(local_app_data)
        else:  # Fallback according to KNOWNFOLDERID docs
            _logger.warning("Empty environment variable 'LocalAppData'")
            base_dir = Path(os.environ["UserProfile"]) / "AppData" / "Local"
    elif _is_mac():
        base_dir = Path("~/Library/Logs").expanduser()
    else:
        ## freedesktop.org Base Directory Specification
        xdg_state_home = os.environ.get("XDG_STATE_HOME")
        if xdg_state_home:
            base_dir = Path(xdg_state_home)
        else:
            base_dir = Path(os.environ["HOME"]) / ".local" / "state"
    return base_dir / _PROGRAM_NAME


def _default_user_data_dir() -> Path:
    return Path("~/MUI_DATA").expanduser()

def _parse_lines(option: str) -> List[str]:
    """``ConfigParser`` type converter for separate lines."""
    return [s.strip() for s in option.splitlines() if s]

def _parse_path(path: str) -> Path:
    """``ConfigParser`` type converter for path values.

    Expand user before vars like shell does: ``FOO="~" ; ls $FOO/``
    """
    ## pathlib devs refuse to implement expandvars so convert to Path
    ## after expandvars https://github.com/python/cpython/issues/65500
    return Path(os.path.expandvars(os.path.expanduser(path.strip())))

def _parse_paths(paths: str) -> List[Path]:
    """``ConfigParser`` type converter for a list of paths, one per line."""
    return [_parse_path(s) for s in paths.split('\n') if s]


def _parse_type(full_name) -> Type:
    """``ConfigParser`` type converter for class fully-qualified names.

    Raises:
        ModuleNotFound: if there is no module
        AttributeError: if the class is not present on module
    """
    if '.' in full_name:
        module_name, class_name = full_name.rsplit('.', 1)
    else:
        ## If the fully qualified name does not have a dot, then it is
        ## a builtin type.
        class_name = full_name
        if sys.version_info < (3,):
            module_name = '__builtin__'
        else:
            module_name = 'builtins'

    module = importlib.import_module(module_name)
    return getattr(module, class_name)


## A dict of type converter name to a callable implementing the
## conversion from string.  To be used in the constructor of
## ConfigParser instances.
_type_converters = {
    'lines' : _parse_lines,
    'path' : _parse_path,
    'paths' : _parse_paths,
    'type' : _parse_type,
}


def _is_windows() -> bool:
    return sys.platform in ('win32', 'cygwin')

def _is_mac() -> bool:
    return sys.platform == 'darwin'
