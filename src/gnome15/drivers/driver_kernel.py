#  Gnome15 - Suite of tools for the Logitech G series keyboards and headsets
#  Copyright (C) 2010 Brett Smith <tanktarta@blueyonder.co.uk>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.

import gnome15.g15locale as g15locale
_ = g15locale.get_translation("gnome15-drivers").ugettext

from cStringIO import StringIO
from pyinputevent.uinput import UInputDevice
from pyinputevent.pyinputevent import InputEvent, SimpleDevice
from pyinputevent.keytrans import *
from threading import Thread

import select 
import pyinputevent.scancodes as S
import gnome15.g15driver as g15driver
import gnome15.util.g15scheduler as g15scheduler
import gnome15.util.g15uigconf as g15uigconf
import gnome15.g15globals as g15globals
import gnome15.g15uinput as g15uinput
import gconf
import fcntl
import os
import gtk
import cairo
import re
import usb
import fb
from PIL import Image
from PIL import ImageMath
import array
import struct
import dbus
import gobject

# Logging
import logging
logger = logging.getLogger(__name__)

# Driver information (used by driver selection UI)
id = "kernel"
name = _("Kernel Drivers")
description = _("Requires ali123's Logitech Kernel drivers. This method requires no other \
daemons to be running, and works with the G13, G15, G19 and G110 keyboards. ")
has_preferences = True


"""
This dictionaries map the default codes emitted by the input system to the
Gnome15 codes.
"""  
g19_key_map = {
               S.KEY_PROG1 : g15driver.G_KEY_M1,
               S.KEY_PROG2 : g15driver.G_KEY_M2,
               S.KEY_PROG3 : g15driver.G_KEY_M3,
               S.KEY_RECORD : g15driver.G_KEY_MR,
               S.KEY_MENU : g15driver.G_KEY_MENU,
               S.KEY_UP : g15driver.G_KEY_UP,
               S.KEY_DOWN : g15driver.G_KEY_DOWN,
               S.KEY_LEFT : g15driver.G_KEY_LEFT,
               S.KEY_RIGHT : g15driver.G_KEY_RIGHT,
               S.KEY_OK : g15driver.G_KEY_OK,
               S.KEY_BACK : g15driver.G_KEY_BACK,
               S.KEY_FORWARD : g15driver.G_KEY_SETTINGS,
               228 : g15driver.G_KEY_LIGHT,
               S.KEY_F1 : g15driver.G_KEY_G1,
               S.KEY_F2 : g15driver.G_KEY_G2,
               S.KEY_F3 : g15driver.G_KEY_G3,
               S.KEY_F4 : g15driver.G_KEY_G4,
               S.KEY_F5 : g15driver.G_KEY_G5,
               S.KEY_F6 : g15driver.G_KEY_G6,
               S.KEY_F7 : g15driver.G_KEY_G7,
               S.KEY_F8 : g15driver.G_KEY_G8,
               S.KEY_F9 : g15driver.G_KEY_G9,
               S.KEY_F10 : g15driver.G_KEY_G10,
               S.KEY_F11 : g15driver.G_KEY_G11,
               S.KEY_F12 : g15driver.G_KEY_G12,
               S.KEY_MUTE : g15driver.G_KEY_MUTE,
               S.KEY_VOLUMEDOWN : g15driver.G_KEY_VOL_DOWN,
               S.KEY_VOLUMEUP  : g15driver.G_KEY_VOL_UP,
               S.KEY_NEXTSONG  : g15driver.G_KEY_NEXT,
               S.KEY_PREVIOUSSONG  : g15driver.G_KEY_PREV,
               S.KEY_PLAYPAUSE : g15driver.G_KEY_PLAY,
               S.KEY_STOPCD : g15driver.G_KEY_STOP,
               }
g15_key_map = {
               S.KEY_PROG1 : g15driver.G_KEY_M1,
               S.KEY_PROG2 : g15driver.G_KEY_M2,
               S.KEY_PROG3 : g15driver.G_KEY_M3,
               S.KEY_RECORD : g15driver.G_KEY_MR,
               S.KEY_OK : g15driver.G_KEY_L1,
               S.KEY_LEFT : g15driver.G_KEY_L2,
               S.KEY_UP : g15driver.G_KEY_L3,
               S.KEY_DOWN : g15driver.G_KEY_L4,
               S.KEY_RIGHT : g15driver.G_KEY_L5,
               228 : g15driver.G_KEY_LIGHT,
               S.KEY_F1 : g15driver.G_KEY_G1,
               S.KEY_F2 : g15driver.G_KEY_G2,
               S.KEY_F3 : g15driver.G_KEY_G3,
               S.KEY_F4 : g15driver.G_KEY_G4,
               S.KEY_F5 : g15driver.G_KEY_G5,
               S.KEY_F6 : g15driver.G_KEY_G6,
               S.KEY_F7 : g15driver.G_KEY_G7,
               S.KEY_F8 : g15driver.G_KEY_G8,
               S.KEY_F9 : g15driver.G_KEY_G9,
               S.KEY_F10 : g15driver.G_KEY_G10,
               S.KEY_F11 : g15driver.G_KEY_G11,
               S.KEY_F12 : g15driver.G_KEY_G12,
               S.KEY_F13 : g15driver.G_KEY_G13,
               S.KEY_F14 : g15driver.G_KEY_G14,
               S.KEY_F15 : g15driver.G_KEY_G15,
               S.KEY_F16 : g15driver.G_KEY_G16,
               S.KEY_F17 : g15driver.G_KEY_G17,
               S.KEY_F18 : g15driver.G_KEY_G18
               }

g15v2_key_map = {
               S.KEY_PROG1 : g15driver.G_KEY_M1,
               S.KEY_PROG2 : g15driver.G_KEY_M2,
               S.KEY_PROG3 : g15driver.G_KEY_M3,
               S.KEY_RECORD : g15driver.G_KEY_MR,
               S.KEY_OK : g15driver.G_KEY_L1,
               S.KEY_LEFT : g15driver.G_KEY_L2,
               S.KEY_UP : g15driver.G_KEY_L3,
               S.KEY_DOWN : g15driver.G_KEY_L4,
               S.KEY_RIGHT : g15driver.G_KEY_L5,
               228 : g15driver.G_KEY_LIGHT,
               S.KEY_F1 : g15driver.G_KEY_G1,
               S.KEY_F2 : g15driver.G_KEY_G2,
               S.KEY_F3 : g15driver.G_KEY_G3,
               S.KEY_F4 : g15driver.G_KEY_G4,
               S.KEY_F5 : g15driver.G_KEY_G5,
               S.KEY_F6 : g15driver.G_KEY_G6
               }
g13_key_map = {
               S.KEY_PROG1 : g15driver.G_KEY_M1,
               S.KEY_PROG2 : g15driver.G_KEY_M2,
               S.KEY_PROG3 : g15driver.G_KEY_M3,
               S.KEY_RECORD : g15driver.G_KEY_MR,
               S.KEY_OK : g15driver.G_KEY_L1,
               S.KEY_LEFT : g15driver.G_KEY_L2,
               S.KEY_UP : g15driver.G_KEY_L3,
               S.KEY_DOWN : g15driver.G_KEY_L4,
               S.KEY_RIGHT : g15driver.G_KEY_L5,
               228 : g15driver.G_KEY_LIGHT,
               S.KEY_F1 : g15driver.G_KEY_G1,
               S.KEY_F2 : g15driver.G_KEY_G2,
               S.KEY_F3 : g15driver.G_KEY_G3,
               S.KEY_F4 : g15driver.G_KEY_G4,
               S.KEY_F5 : g15driver.G_KEY_G5,
               S.KEY_F6 : g15driver.G_KEY_G6,
               S.KEY_F7 : g15driver.G_KEY_G7,
               S.KEY_F8 : g15driver.G_KEY_G8,
               S.KEY_F9 : g15driver.G_KEY_G9,
               S.KEY_F10 : g15driver.G_KEY_G10,
               S.KEY_F11 : g15driver.G_KEY_G11,
               S.KEY_F12 : g15driver.G_KEY_G12,
               S.KEY_F13 : g15driver.G_KEY_G13,
               S.KEY_F14 : g15driver.G_KEY_G14,
               S.KEY_F15 : g15driver.G_KEY_G15,
               S.KEY_F16 : g15driver.G_KEY_G16,
               S.KEY_F17 : g15driver.G_KEY_G17,
               S.KEY_F18 : g15driver.G_KEY_G18,
               S.KEY_F19 : g15driver.G_KEY_G19,
               S.KEY_F20 : g15driver.G_KEY_G20,
               S.KEY_F21 : g15driver.G_KEY_G21,
               S.KEY_F22 : g15driver.G_KEY_G22,
               S.BTN_X: g15driver.G_KEY_JOY_LEFT,                  
               S.BTN_Y: g15driver.G_KEY_JOY_DOWN,                     
               S.BTN_Z: g15driver.G_KEY_JOY_CENTER,
               }
g110_key_map = {
               S.KEY_PROG1 : g15driver.G_KEY_M1,
               S.KEY_PROG2 : g15driver.G_KEY_M2,
               S.KEY_PROG3 : g15driver.G_KEY_M3,
               S.KEY_RECORD : g15driver.G_KEY_MR,
               228 : g15driver.G_KEY_LIGHT,
               S.KEY_F1 : g15driver.G_KEY_G1,
               S.KEY_F2 : g15driver.G_KEY_G2,
               S.KEY_F3 : g15driver.G_KEY_G3,
               S.KEY_F4 : g15driver.G_KEY_G4,
               S.KEY_F5 : g15driver.G_KEY_G5,
               S.KEY_F6 : g15driver.G_KEY_G6,
               S.KEY_F7 : g15driver.G_KEY_G7,
               S.KEY_F8 : g15driver.G_KEY_G8,
               S.KEY_F9 : g15driver.G_KEY_G9,
               S.KEY_F10 : g15driver.G_KEY_G10,
               S.KEY_F11 : g15driver.G_KEY_G11,
               S.KEY_F12 : g15driver.G_KEY_G12
               }
g510_key_map = {
               S.KEY_PROG1 : g15driver.G_KEY_M1,
               S.KEY_PROG2 : g15driver.G_KEY_M2,
               S.KEY_PROG3 : g15driver.G_KEY_M3,
               S.KEY_RECORD : g15driver.G_KEY_MR,
               S.KEY_OK : g15driver.G_KEY_L1,
               S.KEY_LEFT : g15driver.G_KEY_L2,
               S.KEY_UP : g15driver.G_KEY_L3,
               S.KEY_DOWN : g15driver.G_KEY_L4,
               S.KEY_RIGHT : g15driver.G_KEY_L5,
               228 : g15driver.G_KEY_LIGHT,
               S.KEY_F1 : g15driver.G_KEY_G1,
               S.KEY_F2 : g15driver.G_KEY_G2,
               S.KEY_F3 : g15driver.G_KEY_G3,
               S.KEY_F4 : g15driver.G_KEY_G4,
               S.KEY_F5 : g15driver.G_KEY_G5,
               S.KEY_F6 : g15driver.G_KEY_G6,
               S.KEY_F7 : g15driver.G_KEY_G7,
               S.KEY_F8 : g15driver.G_KEY_G8,
               S.KEY_F9 : g15driver.G_KEY_G9,
               S.KEY_F10 : g15driver.G_KEY_G10,
               S.KEY_F11 : g15driver.G_KEY_G11,
               S.KEY_F12 : g15driver.G_KEY_G12,
               S.KEY_F13 : g15driver.G_KEY_G13,
               S.KEY_F14 : g15driver.G_KEY_G14,
               S.KEY_F15 : g15driver.G_KEY_G15,
               S.KEY_F16 : g15driver.G_KEY_G16,
               S.KEY_F17 : g15driver.G_KEY_G17,
               S.KEY_F18 : g15driver.G_KEY_G18
               }

g19_mkeys_control = g15driver.Control("mkeys", _("Memory Bank Keys"), 0, 0, 15, hint=g15driver.HINT_MKEYS)
g19_keyboard_backlight_control = g15driver.Control("backlight_colour", _("Keyboard Backlight Colour"), (0, 255, 0), hint=g15driver.HINT_DIMMABLE | g15driver.HINT_SHADEABLE)

g19_brightness_control = g15driver.Control("lcd_brightness", _("LCD Brightness"), 100, 0, 100, hint = g15driver.HINT_SHADEABLE)
g19_foreground_control = g15driver.Control("foreground", _("Default LCD Foreground"), (255, 255, 255), hint=g15driver.HINT_FOREGROUND | g15driver.HINT_VIRTUAL)
g19_background_control = g15driver.Control("background", _("Default LCD Background"), (0, 0, 0), hint=g15driver.HINT_BACKGROUND | g15driver.HINT_VIRTUAL)
g19_highlight_control = g15driver.Control("highlight", _("Default Highlight Color"), (255, 0, 0), hint=g15driver.HINT_HIGHLIGHT | g15driver.HINT_VIRTUAL)
g19_controls = [ g19_brightness_control, g19_keyboard_backlight_control, g19_foreground_control, g19_background_control, g19_highlight_control, g19_mkeys_control ]

g110_keyboard_backlight_control = g15driver.Control("backlight_colour", _("Keyboard Backlight Colour"), (255, 0, 0), hint=g15driver.HINT_DIMMABLE | g15driver.HINT_SHADEABLE | g15driver.HINT_RED_BLUE_LED)
g110_controls = [ g110_keyboard_backlight_control, g19_mkeys_control ]

g15_mkeys_control = g15driver.Control("mkeys", _("Memory Bank Keys"), 1, 0, 15, hint=g15driver.HINT_MKEYS)
g15_backlight_control = g15driver.Control("keyboard_backlight", _("Keyboard Backlight Level"), 2, 0, 2, hint=g15driver.HINT_DIMMABLE)
g15_lcd_backlight_control = g15driver.Control("lcd_backlight", _("LCD Backlight"), 2, 0, 2, g15driver.HINT_SHADEABLE)
g15_lcd_contrast_control = g15driver.Control("lcd_contrast", _("LCD Contrast"), 22, 0, 48, 0)
g15_invert_control = g15driver.Control("invert_lcd", _("Invert LCD"), 0, 0, 1, hint=g15driver.HINT_SWITCH | g15driver.HINT_VIRTUAL)
g15_controls = [ g15_mkeys_control, g15_backlight_control, g15_invert_control, g15_lcd_backlight_control, g15_lcd_contrast_control ]  
g11_controls = [ g15_mkeys_control, g15_backlight_control ]
g13_controls = [ g19_keyboard_backlight_control, g15_mkeys_control, g15_invert_control, g15_mkeys_control ]

"""
Keymaps that are sent to the kernel driver. These are the codes the driver
will emit.
 
"""
K_KEYMAPS = {
             g15driver.MODEL_G19: {
                                   0x0000 : S.KEY_F1,
                                   0x0001 : S.KEY_F2,
                                   0x0002 : S.KEY_F3,
                                   0x0003 : S.KEY_F4,
                                   0x0004 : S.KEY_F5,
                                   0x0005 : S.KEY_F6,
                                   0x0006 : S.KEY_F7,
                                   0x0007 : S.KEY_F8,
                                   0x0008 : S.KEY_F9,
                                   0x0009 : S.KEY_F10,
                                   0x000A : S.KEY_F11,
                                   0x000B : S.KEY_F12,
                                   0x000C : S.KEY_PROG1,
                                   0x000D : S.KEY_PROG2,
                                   0x000E : S.KEY_PROG3,
                                   0x000F : S.KEY_RECORD,
                                   0x0013 : 228,
                                   0x0018 : S.KEY_FORWARD,
                                   0x0019 : S.KEY_BACK,
                                   0x001A : S.KEY_MENU,
                                   0x001B : S.KEY_OK,
                                   0x001C : S.KEY_RIGHT,
                                   0x001D : S.KEY_LEFT,
                                   0x001E : S.KEY_DOWN,
                                   0x001F : S.KEY_UP                                   
                                   },
             g15driver.MODEL_G15_V1: {
                                   0x00 : S.KEY_F1,
                                   0x02 : S.KEY_F13,
                                   0x07 : 228,
                                   0x08 : S.KEY_F7,
                                   0x09 : S.KEY_F2,
                                   0x0b : S.KEY_F14,
                                   0x0f : S.KEY_LEFT,
                                   0x11 : S.KEY_F8,
                                   0x12 : S.KEY_F3,
                                   0x14 : S.KEY_F15,
                                   0x17 : S.KEY_UP,
                                   0x1a : S.KEY_F9,
                                   0x1b : S.KEY_F4,
                                   0x1d : S.KEY_F16,
                                   0x1f : S.KEY_DOWN,
                                   0x23 : S.KEY_F10,
                                   0x24 : S.KEY_F5,
                                   0x26 : S.KEY_F17,
                                   0x27 : S.KEY_RIGHT,
                                   0x28 : S.KEY_PROG1,
                                   0x2c : S.KEY_F11,
                                   0x2d : S.KEY_F6,
                                   0x31 : S.KEY_PROG2,
                                   0x35 : S.KEY_F12,
                                   0x36 : S.KEY_RECORD,
                                   0x3a : S.KEY_PROG3,
                                   0x3e : S.KEY_F18,
                                   0x3f : S.KEY_OK
                                   },
             g15driver.MODEL_G15_V2: {
                                   0x0000 : S.KEY_F1,
                                   0x0001 : S.KEY_F2,
                                   0x0002 : S.KEY_F3,
                                   0x0003 : S.KEY_F4,
                                   0x0004 : S.KEY_F5,
                                   0x0005 : S.KEY_F6,
                                   0x0006 : S.KEY_PROG1,
                                   0x0007 : S.KEY_PROG2,
                                   0x0008 : 228,
                                   0x0009 : S.KEY_LEFT,
                                   0x000a : S.KEY_UP,
                                   0x000b : S.KEY_DOWN,
                                   0x000c : S.KEY_RIGHT,
                                   0x000d : S.KEY_PROG3,
                                   0x000e : S.KEY_RECORD,
                                   0x000f : S.KEY_OK,
                                   },
            g15driver.MODEL_G13: {
                                   0x0000 : S.KEY_F1,
                                   0x0001 : S.KEY_F2,
                                   0x0002 : S.KEY_F3,
                                   0x0003 : S.KEY_F4,
                                   0x0004 : S.KEY_F5,
                                   0x0005 : S.KEY_F6,
                                   0x0006 : S.KEY_F7,
                                   0x0007 : S.KEY_F8,
                                   0x0008 : S.KEY_F9,
                                   0x0009 : S.KEY_F10,
                                   0x000A : S.KEY_F11,
                                   0x000B : S.KEY_F12,
                                   0x000C : S.KEY_F13,
                                   0x000D : S.KEY_F14,
                                   0x000E : S.KEY_F15,
                                   0x000F : S.KEY_F16,
                                   0x0010 : S.KEY_F17,
                                   0x0011 : S.KEY_F18,
                                   0x0012 : S.KEY_F19,
                                   0x0013 : S.KEY_F20,
                                   0x0014 : S.KEY_F21,
                                   0x0015 : S.KEY_F22,
                                   0x0016 : S.KEY_OK,
                                   0x0017 : S.KEY_LEFT,
                                   0x0018 : S.KEY_UP,
                                   0x0019 : S.KEY_DOWN,
                                   0x001A : S.KEY_RIGHT,
                                   0x001B : S.KEY_PROG1,
                                   0x001C : S.KEY_PROG2,
                                   0x001D : S.KEY_PROG3,
                                   0x001E : S.KEY_RECORD,
                                   0x001F : S.BTN_X,
                                   0x0020 : S.BTN_Y,
                                   0x0021 : S.BTN_Z,
                                   0x0022 : 228,
                                   },
             g15driver.MODEL_G110: {
                                   0x0000 : S.KEY_F1,
                                   0x0001 : S.KEY_F2,
                                   0x0002 : S.KEY_F3,
                                   0x0003 : S.KEY_F4,
                                   0x0004 : S.KEY_F5,
                                   0x0005 : S.KEY_F6,
                                   0x0006 : S.KEY_F7,
                                   0x0007 : S.KEY_F8,
                                   0x0008 : S.KEY_F9,
                                   0x0009 : S.KEY_F10,
                                   0x000A : S.KEY_F11,
                                   0x000B : S.KEY_F12,
                                   0x000C : S.KEY_PROG1,
                                   0x000D : S.KEY_PROG2,
                                   0x000E : S.KEY_PROG3,
                                   0x000F : S.KEY_RECORD,
                                   0x0010 : 228,
                                   },
             g15driver.MODEL_G510: {
                                   0x0000 : S.KEY_F1,
                                   0x0001 : S.KEY_F2,
                                   0x0002 : S.KEY_F3,
                                   0x0003 : S.KEY_F4,
                                   0x0004 : S.KEY_F5,
                                   0x0005 : S.KEY_F6,
                                   0x0006 : S.KEY_F7,
                                   0x0007 : S.KEY_F8,
                                   
                                   0x0008 : S.KEY_F9,
                                   0x0009 : S.KEY_F10,
                                   0x000A : S.KEY_F11,
                                   0x000B : S.KEY_F12,
                                   0x000C : S.KEY_F13,
                                   0x000D : S.KEY_F14,
                                   0x000E : S.KEY_F15,
                                   0x000F : S.KEY_F16,
                                   
                                   0x0010 : S.KEY_F17,
                                   0x0011 : S.KEY_F18,                                   
                                   0x0013 : 228,
                                   0x0014 : S.KEY_PROG1,
                                   0x0015 : S.KEY_PROG2,
                                   0x0016 : S.KEY_PROG3,
                                   0x0017 : S.KEY_RECORD,
                                   
                                   0x0018 : S.KEY_OK,
                                   0x0019 : S.KEY_LEFT,
                                   0x001A : S.KEY_UP,
                                   0x001B : S.KEY_DOWN,
                                   0x001C : S.KEY_RIGHT
                                   
                                   },
             }

# from https://chromium.googlesource.com/chromiumos/third_party/autotest/+/master/client/bin/input/linux_ioctl.py

_IOC_NRBITS   = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14
_IOC_DIRBITS  = 2

_IOC_NRMASK   = ((1 << _IOC_NRBITS) - 1)
_IOC_TYPEMASK = ((1 << _IOC_TYPEBITS) - 1)
_IOC_SIZEMASK = ((1 << _IOC_SIZEBITS) - 1)
_IOC_DIRMASK  = ((1 << _IOC_DIRBITS) - 1)

_IOC_NRSHIFT   = 0
_IOC_TYPESHIFT = (_IOC_NRSHIFT + _IOC_NRBITS)
_IOC_SIZESHIFT = (_IOC_TYPESHIFT + _IOC_TYPEBITS)
_IOC_DIRSHIFT  = (_IOC_SIZESHIFT + _IOC_SIZEBITS)

IOC_NONE  = 0
IOC_WRITE = 1
IOC_READ  = 2

# Return the byte size of a python struct format string
def sizeof(t):
    return struct.calcsize(t)

def IOC(d, t, nr, size):
    return ((d << _IOC_DIRSHIFT) | (ord(t) << _IOC_TYPESHIFT) |
            (nr << _IOC_NRSHIFT) | (size << _IOC_SIZESHIFT))

# used to create numbers
def IO(t, nr, t_format):
    return IOC(IOC_NONE, t, nr, 0)

def IOW(t, nr, t_format):
    return IOC(IOC_WRITE, t, nr, sizeof(t_format))

def IOR(t, nr, t_format):
    return IOC(IOC_READ, t, nr, sizeof(t_format))

# from https://chromium.googlesource.com/chromiumos/third_party/autotest/+/master/client/bin/input/linux_input.py

# struct input_keymap_entry {
#   __u8 flags;
#   __u8 len;
#   __u16 index;
#   __u32 keycode;
#   __u8 scancode[32];
# };
input_keymap_entry_t = 'BBHI32B'
input_keymap_entry_scancode_offset = 'BBHI'

EVIOCGKEYCODE    = IOR('E', 0x04, '2I') # get keycode
EVIOCGKEYCODE_V2 = IOR('E', 0x04, input_keymap_entry_t)
EVIOCSKEYCODE    = IOW('E', 0x04, '2I') # set keycode
EVIOCSKEYCODE_V2 = IOW('E', 0x04, input_keymap_entry_t)


class DeviceInfo:
    def __init__(self, leds, controls, key_map, led_prefix, keydev_pattern, sink_pattern = None, mm_pattern = None):

        """
        This object describes the device specific details this driver needs to know. Mainly
        the file names that are created by the kernel driver and the maps for converting the
        uinput keys codes from the driver into Gnome15 key code.

        Keyword arguments:
        leds             --    a list containing the files names of the 'Memory' keys (M1, M2, M3 and MR).
                               These names match files in /sys/class/leds, prefixed with the value of
                               led_prefix (see below)
        controls         --    a list g15driver.Control objects supported by this device
        key_map          --    a dictionary of UINPUT -> Gnome15 key codes
        led_prefix       --    Each LED file in /sys/class/leds is prefixed by this short model name.  
        keydev_pattern   --    A regular expression that matches the filename of the 'if01' device in 
                               /dev/input/by-id. 'G' Keys, 'M' Keys and 'D' Pad Keys are read from this device.
        sink_pattern     --    Optional. When specified, is a regular expression that matches the filename
                               of the 'keyboard' device in /dev/input/by-id. When specified, the driver
                               will open the device and just ignore any events from it. This fixes the problem
                               of 'F' keys being emitted when keys are pressed.
        mm_pattern       --    Optional. When specified, is a regular expression that matches the filename
                               of the 'multimedia keys' device in /dev/input/by-id. When specified, the driver
                               can open the device to intercept the multimedia keys and interpret them as 
                               Gnome15 macro keys.
        """

        self.leds = leds
        self.controls = controls
        self.key_map = key_map
        self.led_prefix = led_prefix 
        self.sink_pattern = sink_pattern
        self.keydev_pattern = keydev_pattern
        self.mm_pattern = mm_pattern

"""
This dictionary keeps all the device specific details this
drivers needs to know. The key is the model code, the
value is a DeviceInfo object that contains the actual
details
"""
device_info = {
       g15driver.MODEL_G19: DeviceInfo(
            ["orange:m1", "orange:m2", "orange:m3", "red:mr" ],
            g19_controls, g19_key_map, "g19",
            r"usb-Logitech_G19_Gaming_Keyboard-event-if.*",
            r"usb-Logitech_G19_Gaming_Keyboard-.*event-kbd.*",
            r"usb-046d_G19_Gaming_Keyboard-event-if.*"),

       g15driver.MODEL_G11: DeviceInfo(
            ["orange:m1", "orange:m2", "orange:m3", "blue:mr" ],
            g11_controls, g15_key_map, "g15",
            r"G15_Keyboard_G15.*if"),

       g15driver.MODEL_G15_V1: DeviceInfo(
            ["orange:m1", "orange:m2", "orange:m3", "blue:mr" ],
            g15_controls, g15_key_map, "g15",
            r"G15_Keyboard_G15.*if",
            r"G15_Keyboard_G15.*kbd",
            r"usb-Logitech_Logitech_Gaming_Keyboard-event-if.*"),

       g15driver.MODEL_G15_V2: DeviceInfo(
            ["red:m1", "red:m2", "red:m3", "blue:mr" ],
            g15_controls, g15v2_key_map, "g15v2",
            r"G15_GamePanel_LCD-event-if.*",
            r"G15_GamePanel_LCD-event-kdb.*"),

       g15driver.MODEL_G13: DeviceInfo(
            ["red:m1", "red:m2", "red:m3", "red:mr" ],
            g13_controls, g13_key_map, "g13",
            r"_G13-event-mouse"),

       g15driver.MODEL_G110: DeviceInfo(
            ["orange:m1", "orange:m2", "orange:m3", "red:mr" ],
            g110_controls, g110_key_map, "g110",
            r"usb-LOGITECH_G110_G-keys-event-if.*",
            r"usb-LOGITECH_G110_G-keys-event-kbd.*"),

       g15driver.MODEL_G510: DeviceInfo(
            ["orange:m1", "orange:m2", "orange:m3", "red:mr" ],
            g13_controls, g510_key_map, "g510",
            r"G510_Gaming_Keyboard.*event-if.*",
            r"G510_Gaming_Keyboard.*event.*kbd.*"),
       }
        

# Other constants
EVIOCGRAB = 0x40044590

def show_preferences(device, parent, gconf_client):
    prefs = KernelDriverPreferences(device, parent, gconf_client)
    prefs.run()

class KernelDriverPreferences():
    
    def __init__(self, device, parent, gconf_client):
        self.device = device
        
        widget_tree = gtk.Builder()
        widget_tree.add_from_file(os.path.join(g15globals.ui_dir, "driver_kernel.ui"))
        self.window = widget_tree.get_object("KernelDriverSettings")
        self.window.set_transient_for(parent)
        
        self.joy_mode_label = widget_tree.get_object("JoyModeLabel")
        self.joy_mode_combo = widget_tree.get_object("JoyModeCombo")
        self.joy_calibrate = widget_tree.get_object("JoyCalibrate")
        self.grab_multimedia = widget_tree.get_object("GrabMultimedia")
        
        device_model = widget_tree.get_object("DeviceModel")
        device_model.clear()
        device_model.append(["auto"])
        for dev_file in os.listdir("/dev"):
            if dev_file.startswith("fb"):
                device_model.append(["/dev/%s" % dev_file])
                  
        g15uigconf.configure_combo_from_gconf(gconf_client, "/apps/gnome15/%s/fb_device" % device.uid, "DeviceCombo", "auto", widget_tree)
        g15uigconf.configure_combo_from_gconf(gconf_client, "/apps/gnome15/%s/joymode" % device.uid, "JoyModeCombo", "macro", widget_tree)
        g15uigconf.configure_checkbox_from_gconf(gconf_client, "/apps/gnome15/%s/grab_multimedia" % device.uid, "GrabMultimedia", False, widget_tree)
        
        self.grab_multimedia.set_sensitive(device_info[device.model_id].mm_pattern is not None)
        
        # See if jstest-gtk is available to do the calibration
        self.calibrate_available = g15uinput.are_calibration_tools_available() 
            
        self.joy_mode_combo.connect("changed", self._set_available_options)        
        self.joy_calibrate.connect("clicked", self._do_calibrate)
            
        self._set_available_options()
        
    def run(self):
        self.window.run()
        self.window.hide()

    def _set_available_options(self, widget = None):
        self.joy_mode_label.set_sensitive(self.device.model_id == g15driver.MODEL_G13)
        self.joy_mode_combo.set_sensitive(self.device.model_id == g15driver.MODEL_G13)
        self.joy_calibrate.set_sensitive(g15uinput.get_device(self._get_device_type()) is not None and \
                                       self.device.model_id == g15driver.MODEL_G13 and \
                                       self.calibrate_available and \
                                       self.joy_mode_combo.get_active() in [1, 3])
        
    def _get_device_type(self):
        return g15uinput.JOYSTICK if self.joy_mode_combo.get_active() == 1 \
            else g15uinput.DIGITAL_JOYSTICK
            
    def _do_calibrate(self, widget):
        g15uinput.calibrate(self._get_device_type())
    
class KeyboardReceiveThread(Thread):
    def __init__(self, device):
        Thread.__init__(self)
        self._run = True
        self.name = "KeyboardReceiveThread-%s" % device.uid
        self.setDaemon(True)
        self.devices = []
        
    def deactivate(self):
        self._run = False
        for dev in self.devices:
            logger.info("Ungrabbing %d", dev.fileno())
            try :
                fcntl.ioctl(dev.fileno(), EVIOCGRAB, 0)
            except Exception as e:
                logger.info("Failed ungrab.", exc_info = e)
            logger.info("Closing %d", dev.fileno())
            try :
                self.fds[dev.fileno()].close()
            except Exception as e:
                logger.info("Failed close.", exc_info = e)
            logger.info("Stopped %d", dev.fileno())
        logger.info("Stopped all input devices")
        
    def run(self):        
        self.poll = select.poll()
        self.fds = {}
        for dev in self.devices:
            self.poll.register(dev, select.POLLIN | select.POLLPRI | select.POLLHUP | select.POLLNVAL | select.POLLERR)
            fcntl.ioctl(dev.fileno(), EVIOCGRAB, 1)
            self.fds[dev.fileno()] = dev
        while self._run:
            for x, e in self.poll.poll(1000):
                dev = self.fds[x]
                try :
                    if dev:
                        dev.read()
                except OSError as e:
                    logger.debug('Could not read device file', exc_info = e)
                    # Ignore this error if deactivated
                    if self._run:
                        raise e
        logger.info("Thread left")
        
'''
SimpleDevice implementation that does nothing with events. This is used to
work-around a problem where X ends up getting the G19 F-key events
'''
class SinkDevice(SimpleDevice):
    def __init__(self, *args, **kwargs):
        SimpleDevice.__init__(self, *args, **kwargs)
        
    def receive(self, event):
        logger.debug("Sunk event %s", str(event))
            
'''
Abstract input device
'''
class AbstractInputDevice(SimpleDevice):
    def __init__(self, callback, key_map, *args, **kwargs):
        SimpleDevice.__init__(self, *args, **kwargs)
        self.callback = callback
        self.key_map = key_map

    def _event(self, event_code, state):
        if event_code in self.key_map:
            key = self.key_map[event_code]
            self.callback([key], state)
        else:
            logger.warning("Unmapped key for event: %s", event_code)
        
'''
SimpleDevice implementation for handling multi-media keys. 
'''
class MultiMediaDevice(AbstractInputDevice):
    def __init__(self, callback, key_map, *args, **kwargs):
        AbstractInputDevice.__init__(self, callback, key_map, *args, **kwargs)
        
    def receive(self, event):
        if event.etype == S.EV_KEY:
            state = g15driver.KEY_STATE_DOWN if event.evalue == 1 else g15driver.KEY_STATE_UP
            if event.evalue != 2:
                self._event(event.ecode, state)
        elif event.etype == 0:
            return
        else:
            logger.warning("Unhandled event: %s", str(event))

'''
SimpleDevice implementation that translates kernel input events
into Gnome15 key events and forwards them to the registered 
Gnome15 keyboard callback.
'''
class ForwardDevice(AbstractInputDevice):
    def __init__(self, driver, callback, key_map, *args, **kwargs):
        AbstractInputDevice.__init__(self, callback, key_map, *args, **kwargs)
        self.driver = driver
        self.ctrl = False
        self.held_keys = []
        self.alt = False
        self.shift = False
        self.current_x = g15uinput.JOYSTICK_CENTER
        self.digital_down = []
        self.current_y = g15uinput.JOYSTICK_CENTER
        self.last_x = g15uinput.JOYSTICK_CENTER
        self.last_y = g15uinput.JOYSTICK_CENTER
        self.move_timer = None

    def send_all(self, events):
        for event in events:
            logger.debug(" --> %r", event)
            self.udev.send_event(event)

    @property
    def modcode(self):
        code = 0
        if self.shift:
            code += 1
        if self.ctrl:
            code += 2
        if self.alt:
            code += 4
        return code
    
    def receive(self, event): 
        if event.etype == S.EV_ABS:
            if self.driver.joy_mode == g15uinput.JOYSTICK:
                """
                The kernel modules give a joystick position values between 0 and 255.
                The center is at 128.
                The virtual joysticks are set to give values between -127 and 127.
                The center is at 0.
                So we adapt the received values.
                """
                val = event.evalue - g15uinput.DEVICE_JOYSTICK_CENTER
                g15uinput.emit(self.driver.joy_mode, (event.etype, event.ecode), val, False)
            else:
                self._update_joystick(event)                        
        elif event.etype == S.EV_KEY:
            state = g15driver.KEY_STATE_DOWN if event.evalue == 1 else g15driver.KEY_STATE_UP
            if event.ecode in [ S.BTN_X, S.BTN_Y, S.BTN_Z ]:
                if self.driver.joy_mode ==g15uinput.MOUSE:                    
                    g15uinput.emit(g15uinput.MOUSE, self._translate_mouse_buttons(event.ecode), event.evalue, syn=True)                
                elif self.driver.joy_mode == g15uinput.DIGITAL_JOYSTICK:
                    g15uinput.emit(g15uinput.DIGITAL_JOYSTICK, event.ecode, event.evalue, syn=True)              
                elif self.driver.joy_mode == g15uinput.JOYSTICK:
                    g15uinput.emit(g15uinput.JOYSTICK, event.ecode, event.evalue, syn=True)                                
                else:
                    if event.evalue != 2:
                        self._event(event.ecode, state)
            else:
                if event.evalue != 2:
                    self._event(event.ecode, state)
        elif event.etype == 0:
            if self.driver.joy_mode == g15uinput.JOYSTICK:
                # Just pass-through when in analogue joystick mode
                g15uinput.emit(self.driver.joy_mode, ( event.etype, event.ecode ), event.evalue, False)
        else:
            logger.warning("Unhandled event: %s", str(event))
                
    """
    Private
    """         
    
    def _record_current_absolute_position(self, event):
        """
        Update the current_x and current_y positions if this is an 
        absolute movement event
        """
        if event.ecode == S.ABS_X:
            self.current_x = event.evalue - g15uinput.DEVICE_JOYSTICK_CENTER
        if event.ecode == S.ABS_Y:
            self.current_y = event.evalue - g15uinput.DEVICE_JOYSTICK_CENTER
            
    def _update_joystick(self, event):
        """
        Handle a position update event from the joystick, either by translating
        it to mouse movements, digitising it, or emiting macros
        
        Keyword arguments:
        event        --    event
        """
        if self.driver.joy_mode == g15uinput.DIGITAL_JOYSTICK:
            self._record_current_absolute_position(event)
            self._digital_joystick(event)
        elif self.driver.joy_mode == g15uinput.MOUSE:
            low_val = g15uinput.JOYSTICK_CENTER - self.driver.calibration
            high_val = g15uinput.JOYSTICK_CENTER + self.driver.calibration
            
            if event.ecode == S.REL_X:
                self.current_x = event.evalue - g15uinput.DEVICE_JOYSTICK_CENTER
            if event.ecode == S.REL_Y:
                self.current_y = event.evalue - g15uinput.DEVICE_JOYSTICK_CENTER
            
            # Get the amount between the current value and the centre to move
            move_x = 0    
            move_y = 0
            if self.current_x >= high_val:
                move_x = self.current_x - high_val
            elif self.current_x <= low_val:
                move_x = self.current_x - low_val
            if self.current_y >= high_val:
                move_y = self.current_y - high_val
            elif self.current_y <= low_val:
                move_y = self.current_y - low_val
                
            if self.current_x != self.last_x or self.current_y != self.last_y:
                self.last_x = self.current_x
                self.last_y = self.current_y 
                self.move_x = self._clamp(-3, move_x / 8, 3)
                self.move_y = self._clamp(-3, move_y / 8, 3) 
                self._mouse_move()
            else:
                if self.move_timer is not None:                    
                    self.move_timer.cancel()
        else:
            self._emit_macro(event)
            
    def _translate_mouse_buttons(self, ecode):
        """
        Translate the default joystick event codes to default mouse
        event codes
        
        Keyword arguments:
        ecode        --    event code to translate
        """
        if ecode == S.BTN_X:
            return g15uinput.BTN_LEFT
        elif ecode == S.BTN_Y:
            return g15uinput.BTN_RIGHT
        elif ecode == S.BTN_Z:
            return g15uinput.BTN_MIDDLE
            
    def _compute_bounds(self):
        """
        Calculate the distances from the (rough) centre position to the position
        when movement each axis will start emiting events based on the 
        current calibration value.
          
        """
        return (g15uinput.JOYSTICK_CENTER - (self.driver.calibration),
                g15uinput.JOYSTICK_CENTER + (self.driver.calibration))
            
    def _emit_macro(self, event):
        """
        Emit macro keys for joystick positions, so they can be processed as all
        other macro keys are (i.e. assigned to a macro, script, or a different
        uinput key)
        
        Keyword arguments:
        event        --    event 
        """
        low_val, high_val = self._compute_bounds()
        val = event.evalue - g15uinput.DEVICE_JOYSTICK_CENTER
        if event.ecode == S.ABS_X:
            if val < low_val:
                self._release_keys([g15driver.G_KEY_RIGHT])
                if not g15driver.G_KEY_LEFT in self.held_keys:
                    self.callback([g15driver.G_KEY_LEFT], g15driver.KEY_STATE_DOWN)
                    self.held_keys.append(g15driver.G_KEY_LEFT)
            elif val > high_val:
                self._release_keys([g15driver.G_KEY_LEFT])
                if not g15driver.G_KEY_RIGHT in self.held_keys:
                    self.callback([g15driver.G_KEY_RIGHT], g15driver.KEY_STATE_DOWN)
                    self.held_keys.append(g15driver.G_KEY_RIGHT)
            else:                                         
                self._release_keys([g15driver.G_KEY_LEFT,g15driver.G_KEY_RIGHT])    
        if event.ecode == S.ABS_Y:
            if val < low_val:
                self._release_keys([g15driver.G_KEY_DOWN])
                if not g15driver.G_KEY_UP in self.held_keys:
                    self.callback([g15driver.G_KEY_UP], g15driver.KEY_STATE_DOWN)
                    self.held_keys.append(g15driver.G_KEY_UP)                        
            elif val > high_val:
                self._release_keys([g15driver.G_KEY_UP])
                if  not g15driver.G_KEY_DOWN in self.held_keys:
                    self.callback([g15driver.G_KEY_DOWN], g15driver.KEY_STATE_DOWN)
                    self.held_keys.append(g15driver.G_KEY_DOWN)
            else:                                         
                self._release_keys([g15driver.G_KEY_UP,g15driver.G_KEY_DOWN])
                
    def _release_keys(self, keys):
        for k in keys:
            if k in self.held_keys:
                self.callback([k], g15driver.KEY_STATE_UP)
                self.held_keys.remove(k)
    
    def _clamp(self, minimum, x, maximum):
        return max(minimum, min(x, maximum))

    def _mouse_move(self):
        if self.move_x != 0 or self.move_y != 0:
            if self.move_x != 0:
                g15uinput.emit(g15uinput.MOUSE, g15uinput.REL_X, self.move_x)        
            if self.move_y != 0:
                g15uinput.emit(g15uinput.MOUSE, g15uinput.REL_Y, self.move_y)
            self.move_timer = g15scheduler.schedule("MouseMove", 0.1, self._mouse_move)
        
    def _digital_joystick(self, event):
        low_val, high_val = self._compute_bounds()
        val = event.evalue - g15uinput.DEVICE_JOYSTICK_CENTER
        if event.ecode == S.ABS_X:
            if val < low_val and not "l" in self.digital_down:
                self.digital_down.append("l")
                g15uinput.emit(g15uinput.DIGITAL_JOYSTICK,
                               g15uinput.ABS_X,
                               g15uinput.JOYSTICK_MIN)
            elif val > high_val and not "r" in self.digital_down:
                self.digital_down.append("r")
                g15uinput.emit(g15uinput.DIGITAL_JOYSTICK,
                               g15uinput.ABS_X,
                               g15uinput.JOYSTICK_MAX)
            elif val >= low_val and val <= high_val and "l" in self.digital_down:
                self.digital_down.remove("l")
                g15uinput.emit(g15uinput.DIGITAL_JOYSTICK,
                               g15uinput.ABS_X,
                               g15uinput.JOYSTICK_CENTER)
            elif val >= low_val and val <= high_val and "r" in self.digital_down:
                self.digital_down.remove("r")
                g15uinput.emit(g15uinput.DIGITAL_JOYSTICK,
                               g15uinput.ABS_X,
                               g15uinput.JOYSTICK_CENTER)
        if event.ecode == S.ABS_Y:
            if val < low_val and not "u" in self.digital_down:
                self.digital_down.append("u")
                g15uinput.emit(g15uinput.DIGITAL_JOYSTICK,
                               g15uinput.ABS_Y,
                               g15uinput.JOYSTICK_MIN)
            elif val > high_val and not "d" in self.digital_down:
                self.digital_down.append("d")
                g15uinput.emit(g15uinput.DIGITAL_JOYSTICK,
                               g15uinput.ABS_Y,
                               g15uinput.JOYSTICK_MAX)
            if val >= low_val and val <= high_val and "u" in self.digital_down:
                self.digital_down.remove("u")
                g15uinput.emit(g15uinput.DIGITAL_JOYSTICK,
                               g15uinput.ABS_Y,
                               g15uinput.JOYSTICK_CENTER)
            elif val >= low_val and val <= high_val and "d" in self.digital_down:
                self.digital_down.remove("d")
                g15uinput.emit(g15uinput.DIGITAL_JOYSTICK,
                               g15uinput.ABS_Y,
                               g15uinput.JOYSTICK_CENTER)

class Driver(g15driver.AbstractDriver):

    def __init__(self, device, on_close=None):
        g15driver.AbstractDriver.__init__(self, "kernel")
        self.notify_handles = []
        self.fb = None
        self.var_info = None
        self.on_close = on_close
        self.key_thread = None
        self.device = device
        self.device_info = None
        self.system_service = None
        self.conf_client = gconf.client_get_default()
        
        try:
            self._init_device()
        except Exception as e:
            # Reset the framebuffer choice back to auto if the requested device does not exist
            if self.device_name != None and self.device_name != "" or self.device_name != "auto":
                self.conf_client.set_string("/apps/gnome15/%s/fb_device" % self.device.uid, "auto")
                self._init_device()
            else:            
                logger.warning("Could not open %s.", self.device_name, exc_info = e)
                
        self.notify_handles.append(self.conf_client.notify_add("/apps/gnome15/%s/joymode" % self.device.uid, self._config_changed, None))
        self.notify_handles.append(self.conf_client.notify_add("/apps/gnome15/%s/fb_device" % self.device.uid, self._framebuffer_device_changed, None))
        self.notify_handles.append(self.conf_client.notify_add("/apps/gnome15/%s/grab_multimedia" % self.device.uid, self._config_changed, None))
    
    def get_antialias(self):         
        if self.device.bpp != 1:
            return cairo.ANTIALIAS_DEFAULT
        else:
            return cairo.ANTIALIAS_NONE
        
    def is_connected(self):
        return self.system_service != None
    
    def get_model_names(self):
        return device_info.keys()
            
    def get_name(self):
        return "Linux Logitech Kernel Driver"
    
    def get_model_name(self):
        return self.device.model_id if self.device != None else None
    
    def get_action_keys(self):
        return self.device.action_keys
        
    def get_key_layout(self):
        if self.get_model_name() == g15driver.MODEL_G13 and "macro" == self.conf_client.get_string("/apps/gnome15/%s/joymode" % self.device.uid):
            """
            This driver with the G13 supports some additional keys
            """
            l = list(self.device.key_layout)
            l.append([ g15driver.G_KEY_UP ])
            l.append([ g15driver.G_KEY_JOY_LEFT, g15driver.G_KEY_LEFT, g15driver.G_KEY_JOY_CENTER, g15driver.G_KEY_RIGHT ])
            l.append([ g15driver.G_KEY_JOY_DOWN, g15driver.G_KEY_DOWN ])
            return l
        elif self.device_info.mm_pattern is not None and self.grab_multimedia:
            l = list(self.device.key_layout)
            l.append([])
            l.append([ g15driver.G_KEY_VOL_UP, g15driver.G_KEY_VOL_DOWN, g15driver.G_KEY_MUTE ])
            l.append([ g15driver.G_KEY_PREV, g15driver.G_KEY_PLAY, g15driver.G_KEY_STOP, g15driver.G_KEY_NEXT ])
            return l
        else:
            return self.device.key_layout
                   
    def _load_configuration(self):
        self.joy_mode = self.conf_client.get_string("/apps/gnome15/%s/joymode" % self.device.uid)
        self.grab_multimedia = self.conf_client.get_bool("/apps/gnome15/%s/grab_multimedia" % self.device.uid)
        if self.joy_mode == g15uinput.MOUSE:
            logger.info("Enabling mouse emulation")
            self.calibration = 20
        elif self.joy_mode == g15uinput.JOYSTICK:
            logger.info("Enabling analogue joystick emulation")            
            self.calibration = 20
        elif self.joy_mode == g15uinput.DIGITAL_JOYSTICK:
            logger.info("Enabling digital joystick emulation")            
            self.calibration = 64
        else:
            logger.info("Enabling macro keys for joystick")
            self.calibration = 64
            
    def _config_changed(self, client, connection_id, entry, args):
        self._reload_and_reconnect()
        
    def _framebuffer_device_changed(self, client, connection_id, entry, args):
        self._reload_and_reconnect()
        
    def get_size(self):
        return self.device.lcd_size
        
    def get_bpp(self):
        return self.device.bpp
    
    def get_controls(self):
        return self.device_info.controls if self.device_info != None else None
    
    def paint(self, img):  
        if not self.fb:
            return 
        width = img.get_width()
        height = img.get_height()
        character_width = width / 8
        fixed = self.fb.get_fixed_info()
        padding = fixed.line_length - character_width
        file_str = StringIO()
        
        if self.get_model_name() == g15driver.MODEL_G19:
            try:
                back_surface = cairo.ImageSurface (4, width, height)
            except Exception as e:
                logger.debug("Could not create ImageSurface. Trying earlier API.", exc_info = e)
                # Earlier version of Cairo
                back_surface = cairo.ImageSurface (cairo.FORMAT_ARGB32, width, height)
            back_context = cairo.Context (back_surface)
            back_context.set_source_surface(img, 0, 0)
            back_context.set_operator (cairo.OPERATOR_SOURCE);
            back_context.paint()
                
            if back_surface.get_format() == cairo.FORMAT_ARGB32:
                """
                If the creation of the type 4 image failed (i.e. earlier version of Cairo)
                then we have to convert it ourselves. This is slow. 
                
                TODO Replace with C routine 
                """
                file_str = StringIO()
                data = back_surface.get_data()
                for i in range(0, len(data), 4):
                    r = ord(data[i + 2])
                    g = ord(data[i + 1])
                    b = ord(data[i + 0])
                    file_str.write(self.rgb_to_uint16(r, g, b))             
                buf = file_str.getvalue()
            else:   
                buf = str(back_surface.get_data())
        else:
            width, height = self.get_size()
            arrbuf = array.array('B', self.empty_buf)
            
            argb_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            argb_context = cairo.Context(argb_surface)
            argb_context.set_source_surface(img)
            argb_context.paint()
            
            '''
            Now convert the ARGB to a PIL image so it can be converted to a 1 bit monochrome image, with all
            colours dithered. It would be nice if Cairo could do this :( Any suggestions?
            ''' 
            pil_img = Image.frombuffer("RGBA", (width, height), argb_surface.get_data(), "raw", "RGBA", 0, 1)
            pil_img = ImageMath.eval("convert(pil_img,'1')",pil_img=pil_img)
            pil_img = ImageMath.eval("convert(pil_img,'P')",pil_img=pil_img)
            pil_img = pil_img.point(lambda i: i >= 250,'1')
            
            # Invert the screen if required
            if g15_invert_control.value == 0:            
                pil_img = pil_img.point(lambda i: 1^i)
            
            # Data is 160x43, 1 byte per pixel. Will have value of 0 or 1.
            width, height = self.get_size()
            data = list(pil_img.getdata())
            fixed = self.fb.get_fixed_info()
            v = 0
            b = 1
            
            # TODO Replace with C routine
            for row in range(0, height):
                for col in range(0, width):
                    if data[( row * width ) + col]:
                        v += b
                    b = b << 1
                    if b == 256:
                        # Full byte
                        b = 1          
                        i = row * fixed.line_length + col / 8
                        arrbuf[i] = v   
                        v = 0 
            buf = arrbuf.tostring()
                
        if self.fb and self.fb.buffer:
            self.fb.buffer[0:len(buf)] = buf
            
    def process_svg(self, document):  
        if self.get_bpp() == 1:
            for element in document.getroot().iter():
                style = element.get("style")
                if style != None:
                    element.set("style", style.replace("font-family:Sans", "font-family:%s" % g15globals.fixed_size_font_name))
                    
    def on_update_control(self, control):
        if control == g19_keyboard_backlight_control or control == g110_keyboard_backlight_control:
            self._write_to_led("red:bl", control.value[0])
            if control.hint & g15driver.HINT_RED_BLUE_LED == 0:
                self._write_to_led("green:bl", control.value[1])
                self._write_to_led("blue:bl", control.value[2])
            else:
                # The G110 only has red and blue LEDs
                self._write_to_led("blue:bl", control.value[2])
        elif control == g15_backlight_control:
            if self.get_model_name() == g15driver.MODEL_G15_V2:
                # G15v2 has different coloured backlight
                self._write_to_led("orange:keys", control.value)
            else:
                self._write_to_led("blue:keys", control.value)  
        elif control == g15_lcd_backlight_control or control == g19_brightness_control:
            self._write_to_led("white:screen", control.value)          
        elif control == g15_lcd_contrast_control:
            self._write_to_led("contrast:screen", control.value)          
        elif control == g15_mkeys_control or control == g19_mkeys_control:
            self._set_mkey_lights(control.value)
        else:
            if control.hint & g15driver.HINT_VIRTUAL == 0:
                logger.warning("Setting the control " + control.id + " is not yet supported on this model. " + \
                               "Please report this as a bug, providing the contents of your /sys/class/led" + \
                               "directory and the keyboard model you use.")
    
    def grab_keyboard(self, callback):
        if self.key_thread != None:
            raise Exception("Keyboard already grabbed")
        
        # Configure the keymap
        logger.info("Grabbing current keymap settings")
        self.original_keymap = self._get_keymap()
        kernel_keymap_replacement = K_KEYMAPS[self.device.model_id]
        self._set_keymap(kernel_keymap_replacement)
              
        self.key_thread = KeyboardReceiveThread(self.device)
        for devpath in self.keyboard_devices:
            logger.info("Adding input device %s", devpath)
            self.key_thread.devices.append(ForwardDevice(self, callback, self.device_info.key_map, devpath, devpath))
        for devpath in self.sink_devices:
            logger.info("Adding input sink device %s", devpath)
            self.key_thread.devices.append(SinkDevice(devpath, devpath))
        for devpath in self.mm_devices:
            logger.info("Adding input multi-media device %s", devpath)
            self.key_thread.devices.append(MultiMediaDevice(callback, self.device_info.key_map, devpath, devpath))
        self.key_thread.start()
        
    '''
    Private
    '''
        
    def _on_connect(self):
        self.notify_handles = []
        # Check hardware again
        self._init_driver()

        # Sanity check        
        if not self.device:
            raise usb.USBError("No supported logitech keyboards found on USB bus")
        if self.device == None:
            raise usb.USBError("WARNING: Found no " + self.model + " Logitech keyboard, Giving up")
        
        # If there is no LCD for this device, don't open the framebuffer
        if self.device.bpp != 0:
            if self.fb_mode == None or self.device_name == None:
                raise usb.USBError("No matching framebuffer device found")
            if self.fb_mode != self.framebuffer_mode:
                raise usb.USBError("Unexpected framebuffer mode %s, expected %s for device %s" % (self.fb_mode, self.framebuffer_mode, self.device_name))
            
            # Open framebuffer
            logger.info("Using framebuffer %s", self.device_name)
            self.fb = fb.fb_device(self.device_name)
            if logger.isEnabledFor(logging.DEBUG):
                self.fb.dump()
            self.var_info = self.fb.get_var_info()
                    
            # Create an empty string buffer for use with monochrome LCD
            self.empty_buf = ""
            for i in range(0, self.fb.get_fixed_info().smem_len):
                self.empty_buf += chr(0)
            
        # Connect to DBUS        
        system_bus = dbus.SystemBus()
        try:
            system_service_object = system_bus.get_object('org.gnome15.SystemService', '/org/gnome15/SystemService')
        except dbus.DBusException as e:
            logger.debug('D-Bus service not available.', exc_info = e)
            raise Exception("Failed to connect to Gnome15 system service. Is g15-system-service running (as root). \
It should be launched automatically if Gnome15 is installed correctly.")          
        self.system_service = dbus.Interface(system_service_object, 'org.gnome15.SystemService')    
        
        # Centre the joystick by default
        if self.joy_mode in [ g15uinput.JOYSTICK, g15uinput.DIGITAL_JOYSTICK ]:
            g15uinput.emit(self.joy_mode, g15uinput.ABS_X, g15uinput.JOYSTICK_CENTER, False)
            g15uinput.emit(self.joy_mode, g15uinput.ABS_Y, g15uinput.JOYSTICK_CENTER, False)
            g15uinput.syn(self.joy_mode)
        
    def _on_disconnect(self):
        if not self.is_connected():
            raise Exception("Not connected")
        self._stop_receiving_keys()
        if self.fb is not None:
            self.fb.__del__()
            self.fb = None
        if self.on_close != None:
            g15scheduler.schedule("Close", 0, self.on_close, self)
        self.system_service = None
        
    def _reload_and_reconnect(self):
        self._load_configuration()
        if self.is_connected():
            self.disconnect()
            
    def _set_mkey_lights(self, lights):
        if self.device_info.leds:
            leds = self.device_info.leds
            self._write_to_led(leds[0], lights & g15driver.MKEY_LIGHT_1 != 0)        
            self._write_to_led(leds[1], lights & g15driver.MKEY_LIGHT_2 != 0)        
            self._write_to_led(leds[2], lights & g15driver.MKEY_LIGHT_3 != 0)        
            self._write_to_led(leds[3], lights & g15driver.MKEY_LIGHT_MR != 0)
        else:
            logger.warning(" Setting MKey lights on " + self.device.model_id + " not yet supported. " + \
            "Please report this as a bug, providing the contents of your /sys/class/led" + \
            "directory and the keyboard model you use.")
    
    def _stop_receiving_keys(self):
        if self.key_thread != None:            
            # Configure the keymap
            logger.info("Resetting keymap settings back to the way they were")
            self._set_keymap(self.original_keymap)
            
            self.key_thread.deactivate()
            self.key_thread = None
            
    def _do_write_to_led(self, name, value):
        if not self.system_service:
            logger.warning("Attempt to write to LED when not connected")
        else:
            logger.debug("Writing %s to LED %s", value, name)
            self.system_service.SetLight(self.device.uid, name, value)
    
    def _write_to_led(self, name, value):
        gobject.idle_add(self._do_write_to_led, name, value)

    def _set_keymap(self, keymap):
        for devpath in self.keyboard_devices:
            logger.debug("Setting keymap on device %s", devpath)
            fd = open(devpath, "rw")
            try:
                buf = array.array('B', [0] * sizeof(input_keymap_entry_t))
                for scancode, keycode in keymap.items():
                    struct.pack_into(input_keymap_entry_t, buf, 0,
                                     0, # flags
                                     sizeof('I'), # len
                                     0, # index
                                     keycode, # keycode
                                     *([0] * 32))
                    struct.pack_into('I', buf, sizeof(input_keymap_entry_scancode_offset), scancode)

                    fcntl.ioctl(fd, EVIOCSKEYCODE_V2, buf)
                    logger.debug("   key %d := %d", scancode, keycode)
            finally:
                fd.close()

    def _get_keymap(self):
        for devpath in self.keyboard_devices:
            logger.debug("Getting keymap from device %s", devpath)
            fd = open(devpath, "rw")
            try:
                keymap = K_KEYMAPS[self.device.model_id].copy()
                buf = array.array('B', [0] * sizeof(input_keymap_entry_t))
                for scancode in keymap:
                    struct.pack_into(input_keymap_entry_t, buf, 0,
                                     0, # flags
                                     sizeof('I'), # len
                                     0, # index
                                     S.KEY_RESERVED, # keycode
                                     *([0] * 32))
                    struct.pack_into('I', buf, sizeof(input_keymap_entry_scancode_offset), scancode)

                    fcntl.ioctl(fd, EVIOCGKEYCODE_V2, buf)
                    keymap[scancode] = struct.unpack(input_keymap_entry_t, buf)[3]
                    logger.debug("   key %d = %d", scancode, keymap[scancode])
                return keymap
            finally:
                fd.close()
        return None
    
    def _handle_bound_key(self, key):
        logger.info("G key - %d", key)
        return True
        
    def _mode_changed(self, client, connection_id, entry, args):
        if self.is_connected():
            self.disconnect()
    
    def _init_device(self):
        self._load_configuration()
        if not self.device.model_id in device_info:
            return
            
        self.device_info = device_info[self.device.model_id]
        self.fb_mode = None
        self.device_name = None
        self.framebuffer_mode = "NONE"
        
        if self.device.bpp == 0:
            logger.info("Device %s has no framebuffer", self.device.model_id)
        else:
            if self.device.bpp == 1:
                self.framebuffer_mode = "GFB_MONO"
            else:
                self.framebuffer_mode = "GFB_QVGA"
            logger.info("Using %s frame buffer mode", self.framebuffer_mode)
                
            # Determine the framebuffer device to use
            self.device_name = self.conf_client.get_string("/apps/gnome15/%s/fb_device" % self.device.uid)
            if self.device_name == None or self.device_name == "" or self.device_name == "auto":
                for fb in os.listdir("/sys/class/graphics"):
                    if fb != "fbcon":
                        logger.info("Trying %s", fb)
                        device_file = "/sys/class/graphics/%s/device" % fb
                        if os.path.exists(device_file):                        
                            usb_id = os.path.basename(os.path.realpath(device_file)).split(".")[0].split(":")
                            if len(usb_id) > 2:
                                if usb_id[1].lower() == "%04x" % self.device.controls_usb_id[0] and usb_id[2].lower() == "%04x" % self.device.controls_usb_id[1]:
                                    self.device_name = "/dev/%s" % fb
                                    break 
                            
            # If still no device name, give up    
            if self.device_name == None or self.device_name == "" or self.device_name == "auto":
                raise Exception("No frame buffer device specified, and none could be found automatically. Are the kernel modules loaded?")
                            
            # Get the mode of the device
            f = open("/sys/class/graphics/" + os.path.basename(self.device_name) + "/name", "r")
            try :
                self.fb_mode = f.readline().replace("\n", "")
            finally :
                f.close() 
        
    def _init_driver(self):
        self._init_device()
            
        # Try and find the paths for the keyboard devices
        self.keyboard_devices = []
        self.sink_devices = []
        self.mm_devices = []
        
        dir = "/dev/input/by-id"
        for p in os.listdir(dir):
            if re.search(self.device_info.keydev_pattern, p):
                logger.info("Input device %s matches %s", p, self.device_info.keydev_pattern)
                self.keyboard_devices.append(dir + "/" + p)
            if self.device_info.sink_pattern is not None and re.search(self.device_info.sink_pattern, p):
                logger.info("Input sink device %s matches %s", p, self.device_info.sink_pattern)
                self.sink_devices.append(dir + "/" + p)
            if self.grab_multimedia and self.device_info.mm_pattern is not None and re.search(self.device_info.mm_pattern, p):
                logger.info("Input multi-media device %s matches %s", p, self.device_info.mm_pattern)
                self.mm_devices.append(dir + "/" + p)
                
    def __del__(self):
        for h in self.notify_handles:
            self.conf_client.notify_remove(h)
