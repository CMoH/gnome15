#!/usr/bin/env python
 
#        +-----------------------------------------------------------------------------+
#        | GPL                                                                         |
#        +-----------------------------------------------------------------------------+
#        | Copyright (c) Brett Smith <tanktarta@blueyonder.co.uk>                      |
#        |                                                                             |
#        | This program is free software; you can redistribute it and/or               |
#        | modify it under the terms of the GNU General Public License                 |
#        | as published by the Free Software Foundation; either version 2              |
#        | of the License, or (at your option) any later version.                      |
#        |                                                                             |
#        | This program is distributed in the hope that it will be useful,             |
#        | but WITHOUT ANY WARRANTY; without even the implied warranty of              |
#        | MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the               |
#        | GNU General Public License for more details.                                |
#        |                                                                             |
#        | You should have received a copy of the GNU General Public License           |
#        | along with this program; if not, write to the Free Software                 |
#        | Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA. |
#        +-----------------------------------------------------------------------------+
   
"""
Page priorities
""" 
PRI_POPUP=999
PRI_EXCLUSIVE=100
PRI_HIGH=99
PRI_NORMAL=50
PRI_LOW=20
PRI_INVISIBLE=0

"""
Default actions
"""
NEXT_SELECTION = "next-sel"
PREVIOUS_SELECTION = "prev-sel"
NEXT_PAGE = "next-page"
PREVIOUS_PAGE = "prev-page"
SELECT = "select"
VIEW = "view"
CLEAR = "clear"
MENU = "menu"

"""
Simple colors
"""
COLOURS = [(0, 0, 0), (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255), (0, 255, 255), (255, 255, 255)]

import g15driver
import g15util
import g15profile
import g15globals
import g15drivermanager
import g15theme
import time
import threading
import cairo
import gconf
import os.path
import traceback
import sys
import logging
from threading import RLock
from g15exceptions import NotConnectedException
logger = logging.getLogger("screen")
        
class ScreenChangeAdapter():
    def memory_bank_changed(self, new_bank_number):
        pass
    
    def attention_cleared(self):
        pass
    
    def attention_requested(self, message):
        pass
    
    def driver_disconnected(self, driver):
        pass
    
    def driver_connected(self, driver):
        pass
    
    def deleting_page(self, page):
        pass
    
    def deleted_page(self, page):
        pass
    
    def new_page(self, page):
        pass
    
    def title_changed(self, page, title):
        pass
    
    def page_changed(self, page):
        pass
    
    
class G15Screen():
    
    def __init__(self, plugin_manager_module, service, device):
        self.service = service
        self.plugin_manager_module = plugin_manager_module
        self.device = device
        self.driver = None
        self.screen_change_listeners = []
        self.local_data = threading.local()
        self.local_data.surface = None
        self.key_handlers = []
        self.plugins = []
        self.conf_client = service.conf_client
        self.notify_handles = []
        self.connection_lock = RLock()
        self.defeat_profile_change = 0
        self.first_page = None
        self.attention_message = g15globals.name
        self.attention = False
        self.splash = None
        self.active_key_state = {}
        self.reschedule_lock = RLock()        
        self.last_error = None
        self.loading_complete = False
        self.control_handles = []
        self.color_no = 1
        self.cycle_timer = None
        self._started_plugins = False
        self.stopping = False
        self.reconnect_timer = None
        self.plugins = self.plugin_manager_module.G15Plugins(self)
        self.mkey_lights_control = None
        self.pages = []
        self.keys_held = {}
        self.action_listeners = []
        
        if not self._load_driver():
            raise Exception("Driver failed to load")
        
    def active_session_changed(self, active):
        if not active and self.driver != None and self.driver.is_connected():
            logger.info("Session now inactive, disconnecting from driver")
            self.plugins.deactivate()
            self.driver.disconnect()
        elif active and ( self.driver == None or not self.driver.is_connected() ):
            self.attempt_connection()
        
    def application_changed(self, view):
        if self.defeat_profile_change < 1:
            choose_profile = None
            title = view.Name()                                    
            # Active window has changed, see if we have a profile that matches it
            for profile in g15profile.get_profiles(self.device):
                if not profile.get_default() and profile.activate_on_focus and len(profile.window_name) > 0 and title.lower().find(profile.window_name.lower()) != -1:
                    choose_profile = profile 
                    break
                
            # No applicable profile found. Look for a default profile, and see if it is set to activate by default
            active_profile = g15profile.get_active_profile(self.device)
            if choose_profile == None:
                default_profile = g15profile.get_default_profile(self.device)
                
                if (active_profile == None or active_profile.id != default_profile.id) and default_profile.activate_on_focus:
                    default_profile.make_active()
            elif active_profile == None or choose_profile.id != active_profile.id:
                choose_profile.make_active()
        
    def start(self):
        logger.info("Starting %s." % self.device.uid)
        
        # Start the driver
        self.attempt_connection() 
        
        # Monitor gconf
        screen_key = "/apps/gnome15/%s" % self.device.uid
        logger.info("Watching GConf settings in %s" % screen_key)
        self.conf_client.add_dir(screen_key, gconf.CLIENT_PRELOAD_NONE)
        self.notify_handles.append(self.conf_client.notify_add("%s/cycle_screens" % screen_key, self.resched_cycle))
        self.notify_handles.append(self.conf_client.notify_add("%s/active_profile" % screen_key, self.active_profile_changed))
        self.notify_handles.append(self.conf_client.notify_add("%s/driver" % screen_key, self.driver_changed))
        for control in self.driver.get_controls():
            self.notify_handles.append(self.conf_client.notify_add("%s/%s" % ( screen_key, control.id ), self._control_changed))
        logger.info("Starting for %s is complete." % self.device.uid)
        
    def stop(self):        
        self.stopping = True
        if self.driver and self.driver.is_connected():
            self.driver.disconnect()
        if self.is_active() and self.driver.get_bpp() > 0:
            self.fade(True)
        g15util.stop_queue("redrawQueue")
        if self.plugins:
            self.plugins.deactivate()
            self.plugins.destroy()
        for h in self.notify_handles:
            self.conf_client.notify_remove(h)
        
    def add_screen_change_listener(self, screen_change_listener):
        if not screen_change_listener in self.screen_change_listeners:
            self.screen_change_listeners.append(screen_change_listener)
        
    def remove_screen_change_listener(self, screen_change_listener):
        if screen_change_listener in self.screen_change_listeners:
            self.screen_change_listeners.remove(screen_change_listener)
        
    def set_available_size(self, size):
        self.available_size = size
        self.redraw()
        
    def get_mkey(self):
        return self.mkey
        
    def set_mkey(self, mkey):
        logger.info("Setting memory bank to %d" % mkey)
        self.mkey = mkey
        val = 0
        if self.mkey == 1:
            val = g15driver.MKEY_LIGHT_1
        elif self.mkey == 2:
            val = g15driver.MKEY_LIGHT_2
        elif self.mkey == 3:
            val = g15driver.MKEY_LIGHT_3
        self.mkey_lights_control.set_mkey_lights(val)
        self.set_color_for_mkey()
        for listener in self.screen_change_listeners:
            listener.memory_bank_changed(val)  
    
    def handle_key(self, keys, state, post=False):
        self.resched_cycle()
        
        # Event first goes to this objects key handlers
        for h in self.key_handlers:
            if h.handle_key(keys, state, post):
                return True

        # Next it goes to the visible page         
        visible = self.get_visible_page()
        if visible != None:
            for h in visible.key_handlers:
                if h.handle_key(keys, state, post):
                    return True
        
        # Requires long press of L1 to cycle
        if self.defeat_profile_change < 1 and not post and state == g15driver.KEY_STATE_UP:
            if g15driver.G_KEY_M1 in keys:
                self.set_mkey(1)
            elif g15driver.G_KEY_M2 in keys:
                self.set_mkey(2)
            elif g15driver.G_KEY_M3 in keys:
                self.set_mkey(3)
                
        return False
    
    def index(self, page):
        """
        Returns the page index
        
        Keyword arguments:
        page -- page object
        """
        i = 0
        for p in self.pages:
            if p == page:
                return i
            i = i + 1
        return i
    
    def get_page(self, id):
        """
        Return a page object given it's ID
        
        Keyword arguments:
        id -- page ID
        """
        for page in self.pages:
            if page.id == id:
                return page
            
    def clear_popup(self):
        """
        Clear any popup screens that are currently running
        """
        for page in self.pages:
            if page.priority == PRI_POPUP:
                # Drop the priority of other popups
                page.set_priority(PRI_LOW)
                break
    
    def add_page(self, page):
        """
        Add a new page. Returns the G15Page object
        
        Keyword arguments:
        page     --    page to add
        """
        if self.driver.get_bpp() == 0:
            raise Exception("The current device has no suitable output device")
        
        logger.info("Creating new page with %s of priority %d" % (page.id, page.priority))
        self.page_model_lock.acquire()
        try :
            logger.info("Adding page %s" % page.id)
            self.clear_popup()
            if page.priority == PRI_EXCLUSIVE:
                for p in self.pages:
                    if p.priority == PRI_EXCLUSIVE:
                        logger.warning("Another page is already exclusive. Lowering %s to HIGH" % id)
                        page.priority = PRI_HIGH
                        break
            self.pages.append(page)   
            for l in self.screen_change_listeners:
                l.new_page(page) 
            return page
        finally:
            self.page_model_lock.release() 
    
    def new_page(self, painter = None, priority=PRI_NORMAL, on_shown=None, on_hidden=None, on_deleted = None,
                 id="Unknown", thumbnail_painter = None, panel_painter = None, title=None,\
                 theme_properties_callback = None, theme_attributes_callback = None):
        logger.warning("DEPRECATED call to G15Screen.new_page, use G15Screen.add_page instead")
        
        """
        Create a new page. Returns the G15Page object
        
        Keyword arguments:
        painter --  painter function. Will be called with a 'canvas' argument that is a cairo.Context
        priority --  priority of screen, defaults to PRI_NORMAL
        on_shown --  function to call when screen is show. Defaults to None 
        on_hidden --  function to call when screen is hidden. Defaults to None 
        on_deleted --  function to call when screen is deleted. Defaults to None
        id --  id of screen 
        thumbnail_painter --  function to call to paint thumbnails for this page. Defaults to None
        panel_painter -- function to call to paint panel graphics for this page. Defaults to None
        theme_properties_callback -- function to call to get theme properties
        theme_attributes_callback -- function to call to get theme attributes
        """
        if self.driver.get_bpp() == 0:
            raise Exception("The current device has no suitable output device")
        
        logger.info("Creating new page with %s of priority %d" % (id, priority))
        self.page_model_lock.acquire()
        try :
            self.clear_popup()
            if priority == PRI_EXCLUSIVE:
                for page in self.pages:
                    if page.priority == PRI_EXCLUSIVE:
                        logger.warning("Another page is already exclusive. Lowering %s to HIGH" % id)
                        priority = PRI_HIGH
                        break
                    
            page = g15theme.G15Page(id, self, painter, priority, on_shown, on_hidden, on_deleted,\
                           thumbnail_painter, panel_painter, theme_properties_callback,\
                           theme_attributes_callback)
            self.pages.append(page)   
            for l in self.screen_change_listeners:
                l.new_page(page) 
            if title:
                page.set_title(title)
            return page
        finally:
            self.page_model_lock.release()   
            
    def delete_after(self, delete_after, page):
        """
        Delete a page after a given time interval. Returns timer object used for deleting. May be canceled
        
        Keyword arguments:
        delete_after -- interval in seconds (float)
        page -- page object to hide
        """
        if page.id in self.deleting:
            # If the page was already deleting, cancel previous timer
            self.deleting[page.id].cancel()
            del self.deleting[page.id]       
                      
        timer = g15util.schedule("DeleteScreen", delete_after, self.del_page, page)
        self.deleting[page.id] = timer
        return timer
    
    def is_on_timer(self, page):
        '''
        Get if the given page is currently on a revert or delete timer
        
        Keyword arugments:
        page -- page object
        '''
        return page.id in self.reverting or page.id in self.deleting
    
    def set_priority(self, page, priority, revert_after=0.0, delete_after=0.0, do_redraw = True):
        """
        Change the priority of a page, optionally reverting or deleting after a specified time. Returns timer object used for reverting or deleting. May be canceled
        
        Keyword arguments:
        page -- page object to change
        priority -- new priority
        revert_after -- revert the page priority to it's original value after specified number of seconds
        delete_after -- delete the page after specified number of seconds
        do_redraw -- redraw after changing priority. Defaults to True
        """
        self.page_model_lock.acquire()
        try :
            if page != None:
                old_priority = page.priority
                page._do_set_priority(priority)
                if do_redraw:
                    self.redraw()        
                if revert_after != 0.0:
                    # If the page was already reverting, restore the priority and cancel the timer
                    if page.id in self.reverting:
                        old_priority = self.reverting[page.id][0]
                        self.reverting[page.id][1].cancel()
                        del self.reverting[page.id]                                        
                        
                    # Start a new timer to revert                    
                    timer = g15util.schedule("Revert", revert_after, self.set_priority, page, old_priority)
                    self.reverting[page.id] = (old_priority, timer)
                    return timer
                if delete_after != 0.0:       
                    return self.delete_after(delete_after, page)
        finally:
            self.page_model_lock.release()  
            
    def raise_page(self, page):
        """
        Raise the page. If it is LOW priority, it will be turned into a POPUP. If it is any other priority,
        it will be raised to the top of list of all pages that are of the same priority (effectively making
        it visible)
        
        Keyword arguments:
        page - page to raise
        """
        if page.priority == PRI_LOW:
            page.set_priority(PRI_POPUP)
        else:
            page.set_time(time.time())
        self.redraw()
        
    def del_page(self, page):
        """
        Remove the page from the screen. The page will be hidden and the next highest priority page
        displayed.
        
        Keyword arguments:
        page -- page to remove
        """
        self.page_model_lock.acquire()
        try :
            if page != None and page in self.pages:                
                logger.info("Deleting page %s" % page.id)
                   
                # Remove any timers that might be running on this page
                if page.id in self.deleting:
                    self.deleting[page.id].cancel()
                    del self.deleting[page.id]
                if page.id in self.reverting:
                    self.reverting[page.id][1].cancel()
                    del self.reverting[page.id]   
                                       
                for l in self.screen_change_listeners:
                    l.deleting_page(page)                                            
            
                if page == self.visible_page:
                    self.visible_page = None   
                    page._do_on_hidden()
                    
                page.remove_all_children()      
                    
                self.pages.remove(page)  
                page._do_on_deleted()                   
                self.redraw()                   
                for l in self.screen_change_listeners:
                    l.deleted_page(page) 
        finally:
            self.page_model_lock.release()
            
    def get_last_error(self):
        return self.last_error
            
    def should_reconnect(self, exception):
        return isinstance(exception, NotConnectedException) or (len(exception.args) == 2 and isinstance(exception.args[0], int) and exception.args[0] in [ 111, 104 ])
            
    def complete_loading(self):              
        try :           
            logger.info("Activating plugins")
            self.plugins.activate(self.splash.update_splash if self.splash else None) 
            if self.first_page != None:
                page = self.get_page(self.first_page)
                if page:
                    self.raise_page(page)
                    
            logger.info("Grabbing keyboard")
            self.driver.grab_keyboard(self.key_received)
            
            logger.info("Grabbed keyboard")
            self.clear_attention()
                
            if self.splash:
                self.splash.complete()
            self.loading_complete = True
            logger.info("Loading complete")
        except Exception as e:
            if self._process_exception(e):
                raise
        
    def key_received(self, keys, state):
        g15util.schedule("KeyReceived", 0, self._do_key_received, keys, state)
            
    def screen_cycle(self):
        page = self.get_visible_page()
        if page != None and page.priority < PRI_HIGH:
            self.cycle(1)
        else:
            self.resched_cycle()
        
    def resched_cycle(self, arg1=None, arg2=None, arg3=None, arg4=None):
        self.reschedule_lock.acquire()
        try:
            logger.debug("Rescheduling cycle")
            self._cancel_timer()
            cycle_screens = self.conf_client.get_bool("/apps/gnome15/%s/cycle_screens" % self.device.uid)
            active = self.driver != None and self.driver.is_connected() and cycle_screens
            if active and self.cycle_timer == None:
                val = self.conf_client.get("/apps/gnome15/%s/cycle_seconds" % self.device.uid)
                time = 10
                if val != None:
                    time = val.get_int()
                self.cycle_timer = g15util.schedule("CycleTimer", time, self.screen_cycle)
        finally:
            self.reschedule_lock.release()
            
    def cycle_level(self, val, control):
        logger.debug("Cycling of %s level by %d" % (control.id, val))
        level = self.conf_client.get_int("/apps/gnome15/" + control.id)
        level += val
        if level > control.upper - 1:
            level = control.lower
        if level < control.lower - 1:
            level = control.upper
        self.conf_client.set_int("/apps/gnome15/" + control.id, level)
        
    def control_configuration_changed(self, client, connection_id, entry, args):
        key = os.path.basename(entry.key)
        logger.debug("Controls changed %s", str(key))
        if self.driver != None:
            for control in self.driver.get_controls():
                if key == control.id:
                    if isinstance(control.value, int):
                        control.value = entry.value.get_int()
                    else:
                        rgb = entry.value.get_string().split(",")
                        control.value = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
                        
                    self.driver.update_control(control)
                    
                    break
            self.redraw()
        
    def request_defeat_profile_change(self):
        self.defeat_profile_change += 1
        
    def release_defeat_profile_change(self):
        if self.defeat_profile_change < 1:
            raise Exception("Cannot release defeat profile change if not requested")
        self.defeat_profile_change -= 1
        
    def cycle_color(self, val, control):
        logger.debug("Cycling of %s color by %d" % (control.id, val))
        self.color_no += val
        if self.color_no < 0:
            self.color_no = len(COLOURS) - 1
        if self.color_no >= len(COLOURS):
            self.color_no = 0
        color = COLOURS[self.color_no]
        self.conf_client.set_string("/apps/gnome15/" + control.id, "%d,%d,%d" % (color[0], color[1], color[2] ) )
        
    def driver_changed(self, client, connection_id, entry, args):
        if self.reconnect_timer:
            self.reconnect_timer.cancel()
        if self.driver == None or self.driver.id != entry.value.get_string():
            g15util.schedule("DriverChange", 1.0, self._reload_driver)
        
    def active_profile_changed(self, client, connection_id, entry, args):
        # Check if the active profile has change
        new_profile = g15profile.get_active_profile(self.device)
        if new_profile == None:
            self.deactivate_profile()
        else:
            self.activate_profile()
                
        return 1

    def activate_profile(self):
        logger.debug("Activating profile")
        if self.driver and self.driver.is_connected():
            self.set_mkey(1)
    
    def deactivate_profile(self):
        logger.debug("De-activating profile")
        if self.driver and self.driver.is_connected():
            self.set_mkey(0)
        
    def clear_attention(self):
        logger.debug("Clearing attention")
        self.attention = False
        for listener in self.screen_change_listeners:
            listener.attention_cleared()
            
    def request_attention(self, message = None):
        logger.debug("Requesting attention '%s'" % message)
        self.attention = True
        if message != None:
            self.attention_message = message
            
        for listener in self.screen_change_listeners:
            listener.attention_requested(message)

        
    '''
    Private
    '''
                
    def _init_screen(self):
        logger.info("Starting screen")
        self.pages = []
        self.content_surface = None
        self.width = self.driver.get_size()[0]
        self.height = self.driver.get_size()[1]
        
        self.surface = cairo.ImageSurface (cairo.FORMAT_ARGB32, self.width, self.height)
        self.size = ( self.width, self.height )
        self.available_size = (0, 0, self.size[0], self.size[1])
        
        self.page_model_lock = threading.RLock()
        self.visible_page = None
        self.old_canvas = None
        self.transition_function = None
        self.background_painter_function = None
        self.foreground_painter_function = None
        self.painter_function = None
        self.mkey = 1
        self.reverting = { }
        self.deleting = { }
        self._do_redraw()
        
    def _do_key_received(self, keys, state):
        try :            
            # Watch for keys that are being held down
            if state == g15driver.KEY_STATE_DOWN:
                logger.info("Keys %s pressed" % str(keys))
                for k in keys:
                    logger.info("Keys %s held" % str(k))
                    self.keys_held[k] = g15util.schedule("HoldKey%s" % str(k), self.service.key_hold_duration, self.key_received, keys, g15driver.KEY_STATE_HELD)
            elif state == g15driver.KEY_STATE_UP:
                logger.info("Keys %s released" % str(keys))
                for k in self.keys_held.keys():
                    logger.info("Keys %s unheld" % str(k))
                    timer = self.keys_held[k]
                    if timer.is_complete():
                        # Key "hold" completed
                        logger.info("Consuming key %s" %k)
                        keys.remove(k)
                    self.keys_held[k].cancel()
                    del self.keys_held[k]            
            elif state == g15driver.KEY_STATE_HELD:
                logger.info("Keys %s HELD" % str(keys))
                        
            if len(keys) > 0:                     
                
                # See if the screen itself, or the plugins,  want to handle the key 
                if self.handle_key(keys, state, post=False) or self.plugins.handle_key(keys, state, post=False):
                    return        
                
                # Special case for the light key
                if state == g15driver.KEY_STATE_UP:
                    if g15driver.G_KEY_LIGHT in keys and not self.driver.get_model_name() == g15driver.MODEL_G19:
                        self.service.dbus_service._driver_service.CycleKeyboard(1)
        
                    profile = g15profile.get_active_profile(self.device)
                    if profile != None:
                        macro = profile.get_macro(self.get_mkey(), keys)
                        if macro != None:
                            self.service.handle_macro(macro)                
                                    
                # See if there is any 'post' handling by the screen itself or by the plugins
                if not self.handle_key(keys, state, post=True) or self.plugins.handle_key(keys, state, post=True):
                    # See if any action sequences have been type
                    action_keys = self.driver.get_action_keys()
                    if action_keys:
                        if self.active_key_state == None:
                            # An action sequence could be starting
                            if state != g15driver.KEY_STATE_DOWN:
                                logger.warning("Action keys in unexpected state %d" % state)
                            self.active_key_state = {}
                                
                        for k in keys:
                            self.active_key_state[k] = state
                            
                        for action in action_keys:
                            binding = action_keys[action]
                            f = 0
                            for k in binding.keys:
                                if k in self.active_key_state and binding.state == self.active_key_state[k]:
                                    f += 1
                            if f == len(binding.keys): 
                                logger.info("Invoking action '%s'" % binding.action)
                                for l in self.action_listeners:
                                    l.action_performed(binding)
                
                
        except Exception as e:
            logger.error("Error in key handling. %s" % str(e))
#            if logger.level == logging.DEBUG:
            traceback.print_exc(file=sys.stderr)
             
    def _control_changed(self, client, connection_id, entry, args):
        self.driver.set_controls_from_configuration(client)
        if self.visible_page:
            self.visible_page.mark_dirty()
        
    def _cancel_timer(self):
        self.reschedule_lock.acquire()
        try:      
            if self.cycle_timer:
                self.cycle_timer.cancel()
                self.cycle_timer = None  
        finally:
            self.reschedule_lock.release()          
            
    def _process_exception(self, exception):
        self.last_error = exception
        self.request_attention(str(exception))
        self.resched_cycle()   
        self.driver = None      
        if self.should_reconnect(exception):
            if logger.level == logging.DEBUG:
                traceback.print_exc(file=sys.stderr)
            self.reconnect_timer = g15util.schedule("ReconnectTimer", 5.0, self.attempt_connection)
        else:
            traceback.print_exc(file=sys.stderr)
            return True
                
    def _reload_driver(self):
        logger.info("Reloading driver")
        if self.driver and self.driver.is_connected() :
            self.driver.disconnect()
            # Let any clients receive their disconnecting. Driver changes should be rare so this is not a big deal
            time.sleep(2.0)
        self._load_driver()
        if self.driver:
            self.attempt_connection(0.0)
            
    def _load_driver(self): 
        # Get the driver. If it is not configured, configuration will be required at this point
        try :
            self.driver = g15drivermanager.get_driver(self.conf_client, self.device, on_close=self.on_driver_close)
            self.driver.on_driver_options_change = self._reload_driver
            return True
        except Exception as e:
            self._process_exception(e)
            self.driver = None
            return False
        
    def profiles_changed(self, client, connection_id, entry, args):
        self.set_color_for_mkey()
        
    def error(self, error_text=None): 
        self.attention(error_text)

    def on_driver_close(self, driver, retry=True):
        logger.info("Driver closed")
    
        for handle in self.control_handles:
            self.conf_client.notify_remove(handle);
        self.control_handles = []
    
        self.plugins.deactivate()
        
        # Delete any remaining pages
        if self.pages:
            for page in list(self.pages):
                self.del_page(page)

        for listener in self.screen_change_listeners:
            listener.driver_disconnected(driver)
                
        if not self.service.shutting_down and not self.stopping:
            if retry:
                logger.info("Testing if connection should be retried")
                self._process_exception(NotConnectedException("Keyboard driver disconnected."))
        
        self.stopping = False
            
    def is_active(self):
        """
        Get if the driver is active.
        """
        return self.driver != None and self.driver.is_connected()
            
    def is_visible(self, page):
        return self._get_next_page_to_display() == page
    
    def get_visible_page(self):
        return self.visible_page
    
    def has_page(self, page):
        return self.get_page(page.id) != None

    def set_painter(self, painter):
        o_painter = self.painter_function
        self.painter_function = painter
        return o_painter
    
    def set_background_painter(self, background_painter):
        logger.info("Changing background painter to %s" % str(background_painter))
        o_background_painter = self.background_painter_function
        self.background_painter_function = background_painter
        return o_background_painter
    
    def set_foreground_painter(self, foreground_painter):
        logger.info("Changing foreground painter to %s" % str(foreground_painter))
        o_foreground_painter = self.foreground_painter_function
        self.foreground_painter_function = foreground_painter
        return o_foreground_painter
    
    def set_transition(self, transition):
        o_transition = self.transition_function
        self.transition_function = transition
        return o_transition
    
    def cycle_to(self, page, transitions = True):
        g15util.clear_jobs("redrawQueue")
        g15util.execute("redrawQueue", "cycleTo", self._do_cycle_to, page, transitions)
            
    def cycle(self, number, transitions = True):
        g15util.clear_jobs("redrawQueue")
        g15util.execute("redrawQueue", "doCycle", self._do_cycle, number, transitions)
            
    def redraw(self, page = None, direction="up", transitions = True, redraw_content = True):
        if page:
            logger.debug("Redrawing %s" % page.id)
        else:
            logger.debug("Redrawing current page")
#        traceback.print_stack()
        g15util.execute("redrawQueue", "redraw", self._do_redraw, page, direction, transitions, redraw_content)
        
    def set_color_for_mkey(self):
        control = self.driver.get_control_for_hint(g15driver.HINT_DIMMABLE)
        if control != None and not isinstance(control.value, int):
            profile = g15profile.get_active_profile(self.device)
            if profile != None:
                rgb = profile.get_mkey_color(self.mkey)
                if rgb != None:                    
                    control.value = rgb
                    self.driver.update_control(control)
                    return
            self.driver.set_control_from_configuration(control, self.service.conf_client)
            self.driver.update_control(control)
            
    def get_current_surface(self):
        return self.local_data.surface
    
    def get_desktop_scale(self):
        sx = float(self.available_size[2]) / float(self.width)
        sy = float(self.available_size[3]) / float(self.height)
        return min(sx, sy)

    def fade(self, stay_faded=False):
        Fader(self, stay_faded=stay_faded).run()
        
    def attempt_connection(self, delay=0.0):
        logger.debug("Attempting connection" if delay == 0 else "Attempting connection in %f" % delay)
        self.connection_lock.acquire()
        try :            
            if not self.service.session_active:
                logger.debug("Desktop session not active, will not connect to driver")
                return
        
            if self.driver == None:
                if not self._load_driver():
                    raise

            if self.driver.is_connected():
                logger.warning("WARN: Attempt to reconnect when already connected.")
                return
            
            if not self._started_plugins:                
                self.plugins.start()
                self._started_plugins = True
            
            self.loading_complete = False
            self.first_page = self.conf_client.get_string("/apps/gnome15/%s/last_page" % self.device.uid)
            
            if delay != 0.0:
                self.reconnect_timer = g15util.schedule("ReconnectTimer", delay, self.attempt_connection)
                return
                            
            try :
                self.driver.connect() 
                self.driver.light_controls = []
                self.mkey_lights_control = self.driver.acquire_mkey_lights()
                for control in self.driver.get_controls():
                    self.control_handles.append(self.conf_client.notify_add("/apps/gnome15/%s/%s" %( self.device.uid, control.id), self.control_configuration_changed));
                self._init_screen()
                if self.splash == None:
                    if self.driver.get_bpp() > 0:
                        self.splash = G15Splash(self, self.conf_client)
                else:
                    self.splash.update_splash(0, 100, "Starting up ..")
                self.set_mkey(1)
                self.activate_profile()
                self.last_error = None
                for listener in self.screen_change_listeners:
                    listener.driver_connected(self.driver)
                             
                self.complete_loading()

            except Exception as e:
                if self._process_exception(e):
                    raise
        finally:
            self.connection_lock.release()
            
        logger.info("Connection for %s is complete." % self.device.uid)
    
    '''
    Private functions
    '''
    
    def _draw_page(self, visible_page, direction="down", transitions = True, redraw_content = True):
        
        if self.driver == None or not self.driver.is_connected():
            return
        
        # Do not paint if the device has no LCD (i.e. G110)
        if self.driver.get_bpp() == 0:
            return
        
        surface =  self.surface
        
        # If the visible page is changing, creating a new surface. Both surfaces are
        # then passed to any transition functions registered
        if visible_page != self.visible_page: 
            logger.debug("Page has changed, recreating surface")
            if visible_page.priority == PRI_NORMAL:   
                self.service.conf_client.set_string("/apps/gnome15/%s/last_page" % self.device.uid, visible_page.id)      
            surface = cairo.ImageSurface (cairo.FORMAT_ARGB32, self.width, self.height)
            
        self.local_data.surface = surface
        canvas = cairo.Context (surface)
        rgb = self.driver.get_color_as_ratios(g15driver.HINT_BACKGROUND, ( 255, 255, 255 ))
        canvas.set_source_rgb(rgb[0],rgb[1],rgb[2])
        canvas.rectangle(0, 0, self.width, self.height)
        canvas.fill()
        rgb = self.driver.get_color_as_ratios(g15driver.HINT_FOREGROUND, ( 0, 0, 0 ))
        canvas.set_source_rgb(rgb[0],rgb[1],rgb[2])
        self.configure_canvas(canvas)
        
        if self.background_painter_function != None:
            self.background_painter_function(canvas)
                
        old_page = None
        if visible_page != self.visible_page:            
            old_page = self.visible_page
            redraw_content = True
            if self.visible_page != None:
                self.visible_page = visible_page
                old_page._do_on_hidden()
            else:                
                self.visible_page = visible_page
            if self.visible_page != None:
                self.visible_page._do_on_shown()
                    
            self.resched_cycle()
            for l in self.screen_change_listeners:
                l.page_changed(self.visible_page)
            
        # Call the screen's painter
        if self.visible_page != None:
            logger.debug("Drawing page %s (direction = %s, transitions = %s, redraw_content = %s" % ( self.visible_page.id, direction, str(transitions), str(redraw_content)))
        
                     
            # Paint the content to a new surface so it can be cached
            if self.content_surface == None or redraw_content:
                self.content_surface = cairo.ImageSurface (cairo.FORMAT_ARGB32, self.width, self.height)
                content_canvas = cairo.Context(self.content_surface)
                self.configure_canvas(content_canvas)
                self.visible_page.paint(content_canvas)
            
            tx =  self.available_size[0]
            ty =  self.available_size[1]
            
            # Scale to the available space, and center
            sx = float(self.available_size[2]) / float(self.width)
            sy = float(self.available_size[3]) / float(self.height)
            scale = min(sx, sy)
            sx = scale
            sy = scale
            
            if tx == 0 and self.available_size[3] != self.size[1]:
                sx = 1
            
            if ty == 0 and self.available_size[2] != self.size[0]:
                sy = 1
            
            canvas.save()
            canvas.translate(tx, ty)
            canvas.scale(sx, sy)
            canvas.set_source_surface(self.content_surface)
            canvas.paint()
            canvas.restore()
            
        # Now paint the screen's foreground
        if self.foreground_painter_function != None:
            self.foreground_painter_function(canvas)
                
        # Run any transitions
        if transitions and self.transition_function != None and self.old_canvas != None:
            self.transition_function(self.old_surface, surface, old_page, self.visible_page, direction)
            
        # Now apply any global transformations and paint
        
        if self.painter_function != None:
            self.painter_function(surface)
        else:
            self.driver.paint(surface)
            
        self.old_canvas = canvas
        self.old_surface = surface
        
    def configure_canvas(self, canvas):        
        canvas.set_antialias(self.driver.get_antialias())
        fo = cairo.FontOptions()
        fo.set_antialias(self.driver.get_antialias())
        if self.driver.get_antialias() == cairo.ANTIALIAS_NONE:
            fo.set_hint_style(cairo.HINT_STYLE_NONE)
            fo.set_hint_metrics(cairo.HINT_METRICS_OFF)
        canvas.set_font_options(fo)
        return fo
    
    def _do_cycle_to(self, page, transitions = True):            
        self.page_model_lock.acquire()
        try :
            if page.priority == PRI_LOW:
                # Visible until the next popup, or it hides itself
                self.set_priority(page, PRI_POPUP)
            elif page.priority < PRI_LOW:
                self.clear_popup()
                # Up to the page to make itself stay visible
                self._draw_page(page, "down", transitions)
            else: 
                self.clear_popup()
                self._flush_reverts_and_deletes()
                # Cycle within pages of the same priority
                page_list = self._get_pages_of_priority(page.priority)
                direction = "up"
                dir = 1
                diff = page_list.index(page)
                if diff >= ( len(page_list) / 2 ):
                    dir *= -1
                    direction = "down"
                self._cycle_pages(diff, page_list)
                self._do_redraw(page, direction=direction, transitions=transitions)
        finally:
            self.page_model_lock.release()
                
    def _do_cycle(self, number, transitions = True):            
        self.page_model_lock.acquire()
        try :
            self._flush_reverts_and_deletes()
            self._cycle(number, transitions)
            dir = "up"
            if number < 0:
                dir = "down"
            self._do_redraw(self._get_next_page_to_display(), direction=dir, transitions=transitions)
        finally:
            self.page_model_lock.release()
            
    def _get_pages_of_priority(self, priority):
        p_pages = []
        for page in self._sort():
            if page.priority == PRI_NORMAL:
                p_pages.append(page)
        return p_pages
    
    def _cycle_pages(self, number, pages):
        if len(pages) > 0:                    
            if number < 0:
                for p in range(number, 0):                    
                    first_time = pages[0].time
                    for i in range(0, len(pages) - 1):
                        pages[i].set_time(pages[i + 1].time)
                    pages[len(pages) - 1].set_time(first_time)
            else:                         
                for p in range(0, number):
                    last_time = pages[len(pages) - 1].time
                    for i in range(len(pages) - 1, 0, -1):
                        pages[i].set_time(pages[i - 1].time)
                    pages[0].set_time(last_time)
            
    def _cycle(self, number, transitions = True):
        if len(self.pages) > 0:            
            self._cycle_pages(number,  self._get_pages_of_priority(PRI_NORMAL))
                
    def _do_redraw(self, page = None, direction="up", transitions = True, redraw_content = True):
        self.page_model_lock.acquire()   
        try :           
            current_page = self._get_next_page_to_display()
            if page == None or page == current_page:
                self._draw_page(current_page, direction, transitions, redraw_content)
            elif page != None and page.panel_painter != None:
                self._draw_page(current_page, direction, transitions, False)
        finally:
            self.page_model_lock.release()
            
    def _flush_reverts_and_deletes(self):        
        self.page_model_lock.acquire()
        try :
            for page_id in self.reverting:
                (old_priority, timer) = self.reverting[page_id]
                timer.cancel()                
                self.set_priority(self.get_page(page_id), old_priority)
            self.reverting = {}
            for page_id in self.deleting:
                timer = self.deleting[page_id]
                timer.cancel()
                self.del_page(self.get_page(page_id))                
            self.deleting = {}
        finally:
            self.page_model_lock.release()   
        
    def _sort(self):
        return sorted(self.pages, key=lambda page: page.value, reverse=True)
    
    def _get_next_page_to_display(self):
        self.page_model_lock.acquire()
        try :
            srt = sorted(self.pages, key=lambda key: key.value, reverse = True)
            if len(srt) > 0 and srt[0].priority != PRI_INVISIBLE:
                return srt[0]
        finally:            
            self.page_model_lock.release()
    
"""
Fades the screen by inserting a foreground painter that paints a transparent
black rectangle over the top of everything. The opacity is this gradually
increased, creating a fading effect
"""    
class Fader():
    
    def __init__(self, screen, stay_faded=False):
        self.screen = screen
        self.opacity = 0.0
        self.stay_faded = stay_faded
        
    def run(self):
        self.chained_painter = self.screen.set_foreground_painter(self.paint)
        try:
            while self.opacity <= 1.0:
                self.screen.redraw()
                time.sleep(0.02)
        finally:
            if not self.stay_faded:
                self.screen.set_foreground_painter(self.chained_painter)
        
    def paint(self, canvas):
        if self.chained_painter != None:
            self.chained_painter(canvas)
            
        # Fade to black on the G19, or white on everything else
        if self.screen.driver.get_bpp() == 1:
            col = 1.0
        else:
            col = 0.0
        canvas.set_source_rgba(col, col, col, self.opacity)
        canvas.rectangle(0, 0, self.screen.width, self.screen.height)
        canvas.fill()
        self.opacity += 0.025

class G15Splash():
    
    def __init__(self, screen, gconf_client):
        self.screen = screen        
        self.progress = 0.0
        self.text = "Starting up .."
        icon_path = g15util.get_icon_path("gnome15")
        if icon_path == None:
            icon_path = os.path.join(g15globals.icons_dir,"hicolor", "apps", "scalable", "gnome15.svg")
        self.logo = g15util.load_surface_from_file(icon_path)
        self.page = g15theme.G15Page("Splash", self.screen, priority = PRI_EXCLUSIVE, thumbnail_painter=self._paint_thumbnail, \
                                         theme_properties_callback = self._get_properties, theme = g15theme.G15Theme(g15globals.image_dir, "background"))        
        self.screen.add_page(self.page)
        
    def complete(self):
        self.progress = 100
        self.screen.redraw(self.page)
        g15util.schedule("ClearSplash", 2.0, self._hide)
        
    def update_splash(self, value, max, text=None):
        self.progress = (float(value) / float(max)) * 100.0
        self.screen.redraw(self.page)
        if text != None:
            self.text = text
        
    def _get_properties(self):
        return { "version": g15globals.version,
                 "progress": self.progress,
                 "text": self.text
                 }
        
    def _paint_thumbnail(self, canvas, allocated_size, horizontal):
        return g15util.paint_thumbnail_image(allocated_size, self.logo, canvas)
        
    def _hide(self):
        self.screen.del_page(self.page)
        self.screen.redraw()