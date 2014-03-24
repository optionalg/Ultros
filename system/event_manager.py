# coding=utf-8
import logging
from operator import itemgetter
from utils.log import getLogger
from utils.misc import output_exception

from types import FunctionType

__author__ = "Gareth Coles"

from system.decorators import run_async
from system.singleton import Singleton


class EventManager(object):
    """
    The event manager.

    This class is a singleton in charge of managing both events and callbacks.

    Usage goes something like this..

    * For registering an event handler::

        class Plugin:
            def __init__(self):
                self.events = EventManager()
                self.events.add_callback("CallbackName", self, self.callback,
                                         0, False, [], {})

            def callback(self, event):
                pass

    * For firing events::

        events = EventManager()
        e = SomeEvent()

        events.run_callback("Some", e)


    Remember, priority is handled from highest to lowest, in that order.
    Try not to pick a priority that's the same as another plugin - If you do,
    order will fall back to alphabetical plugin name ordering.
    """

    __metaclass__ = Singleton

    #: Storage for all of the callbacks. The internal storage works like this::
    #:
    #:     callbacks = {
    #:         "callback_name": [
    #:             {
    #:                 "name": str(),
    #:                 "priority": int(),
    #:                 "function": func(),
    #:                 "cancelled:" bool(),
    #:                 "filter": func() or None,  # For event filtering
    #:                 "extra_args": [],  # Extra args to pass
    #:                 "extra_kwargs": {}  # Extra kwargs to pass
    #:             }
    #:         ]
    #:     }
    callbacks = {}

    def __init__(self):
        self.logger = getLogger("Events")

    def _sort(self, lst):
        return sorted(lst, key=itemgetter("priority", "name"), reverse=True)

    def add_callback(self, callback, plugin, function, priority, fltr=None,
                     cancelled=False, extra_args=None, extra_kwargs=None):
        """
        Add a callback. Call this from your plugin to handle events.

        Note: A plugin may not have more than one handler for a callback.
        You should register a function to call your handlers in order
        inside your plugin if you need this. A handler handler. Handlerception!

        :param callback: The name of the callback
        :param plugin: Your plugin object's instance (aka self)
        :param function: The callback function
        :param priority: An integer representing where in the order of
                         callbacks the function should be called
        :param fltr: A function that takes one argument (an event) and returns
                     either True or False, which represents whether to handle
                     the event or not. This is optional.
        :param cancelled: Whether to handle cancelled events or not
        :param extra_args: Extra arguments to pass to the handler.
        :param extra_kwargs: Extra keyword arguments to pass to the handler.

        :type callback: str
        :type plugin: Plugin
        :type function: function
        :type priority: int
        :type fltr: function
        :type cancelled: bool
        :type extra_args: list
        :type extra_kwargs: dict
        """
        if extra_args is None:
            extra_args = []
        if extra_kwargs is None:
            extra_kwargs = {}
        if not self.has_callback(callback):
            self.callbacks[callback] = []
        if self.has_plugin_callback(callback, plugin.info.name):
            raise ValueError("Plugin '%s' has already registered a handler for"
                             " the '%s' callback" %
                             (plugin.info.name, callback))

        current = self.callbacks[callback]

        data = {"name": plugin.info.name,
                "function": function,
                "priority": priority,
                "cancelled": cancelled,
                "filter": fltr,
                "extra_args": extra_args,
                "extra_kwargs": extra_kwargs}

        self.logger.debug("Adding callback: %s" % data)

        current.append(data)

        self.callbacks[callback] = self._sort(current)

    def get_callback(self, callback, plugin):
        """
        Get a handler dict for a specific callback, in a specific plugin.

        :param callback: Name of the callback
        :param plugin: Name of the plugin

        :type plugin: str
        :type callback: str

        :return: The callback handler if it exists, otherwise None
        """
        if self.has_callback(callback):
            callbacks = self.get_callbacks(callback)
            for cb in callbacks:
                if cb["name"] == plugin:
                    return cb
            return None
        return None

    def get_callbacks(self, callback):
        """
        Get all handlers (in a list) for a specific callback.

        :param callback: Name of the callback
        :type callback: str

        :return: The list of callback handlers if it exists, otherwise None
        """
        if self.has_callback(callback):
            return self.callbacks[callback]
        return None

    def has_callback(self, callback):
        """
        Check if a callback exists.

        :param callback: Name of the callback
        :type callback: str

        :return: Whether the callback exists
        :rtype: bool
        """
        return callback in self.callbacks

    def has_plugin_callback(self, callback, plugin):
        """
        Check if a plugin registered a handler for a certain callback.

        :param callback: Name of the callback
        :param plugin: Name of the plugin

        :type plugin: str
        :type callback: str

        :return: Whether the callback exists and is registered to that plugin
        :rtype: bool
        """
        if self.has_callback(callback):
            callbacks = self.get_callbacks(callback)
            for cb in callbacks:
                if cb["name"] == plugin:
                    return True
            return False
        return False

    def remove_callback(self, callback, plugin):
        """
        Remove a callback from a plugin.

        :param callback: Name of the callback
        :param plugin: Name of the plugin
        :type plugin: str
        :type callback: str
        """
        if self.has_plugin_callback(callback, plugin):
            callbacks = self.get_callbacks(callback)
            done = []
            for cb in callbacks:
                if not cb["name"] == plugin:
                    done.append(cb)
            if len(done) > 0:
                self.callbacks[callback] = self._sort(done)
            else:
                del self.callbacks[callback]

    def remove_callbacks(self, callback):
        """
        Remove a certain callback.

        :param callback: Name of the callback
        :type callback: str
        """
        if self.has_callback(callback):
            del self.callbacks[callback]

    def remove_callbacks_for_plugin(self, plugin):
        """
        Remove all handlers for a certain plugin.

        :param plugin: Name of the plugin
        :type plugin: str
        """
        current = self.callbacks.items()
        for key, value in current:
            done = []
            for cb in value:
                if not cb["name"] == plugin:
                    done.append(cb)
            if len(done) > 0:
                self.callbacks[key] = self._sort(done)
            else:
                del self.callbacks[key]

    def run_callback(self, callback, event, threaded=False):
        """
        Run all handlers for a certain callback with an event.

        :param callback: The callback to run
        :param event: An instance of the event to pass through the handlers
        :param threaded: Whether to run each callback in its own thread

        :type callback: str
        :type event: object
        :type threaded: bool
        """
        if self.has_callback(callback):

            self.logger.debug("Event: %s" % event)

            for cb in self.get_callbacks(callback):
                if threaded:
                    @run_async
                    def go():
                        """ Run the callback asynchronously """
                        cb["function"](event, *cb["extra_args"],
                                       **cb["extra_kwargs"])
                else:
                    def go():
                        """ Run the callback synchronously """
                        cb["function"](event, *cb["extra_args"],
                                       **cb["extra_kwargs"])
                try:
                    self.logger.debug("Running callback: %s" % cb)
                    if cb["filter"]:
                        if isinstance(cb["filter"], FunctionType):
                            if not cb["filter"](event):
                                self.logger.debug("Not running, filter "
                                                  "function returned false.")
                                continue
                        else:
                            self.logger.warn("Not running event, filter "
                                             "is not actually a function. Bug "
                                             "the developers of the %s plugin "
                                             "about it!" % cb["name"])
                            self.logger.warn("Value: %s" % cb["filter"])
                            continue
                    if event.cancelled:
                        if cb["cancelled"]:
                            go()
                        else:
                            self.logger.debug("Not running, event is cancelled"
                                              " and handler doesn't accept"
                                              " cancelled events")
                    else:
                        go()
                except Exception as e:
                    self.logger.warn("Error running callback '%s': %s" %
                                     (callback, e))
                    output_exception(self.logger, logging.WARN)
        return event
