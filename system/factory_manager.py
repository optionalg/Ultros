# coding=utf-8

__author__ = "Gareth Coles"

import logging
import inspect
import signal

from twisted.internet import reactor

from system.command_manager import CommandManager
from system.constants import *
from system.event_manager import EventManager
from system.events.general import PluginsLoadedEvent, ReactorStartedEvent
from system.factory import Factory
from system.metrics import Metrics
from system.plugin_manager import YamlPluginManagerSingleton
from system.singleton import Singleton
from system.storage.formats import YAML
from system.storage.config import Config
from system.storage.manager import StorageManager

from utils.log import getLogger
from utils.misc import output_exception

from system.translations import Translations
_ = Translations().get()


class Manager(object):
    """
    Manager for keeping track of multiple factories - one per protocol.

    This is so that the bot can connect to multiple services at once, and have
    them communicate with each other.
    """

    __metaclass__ = Singleton

    #: Instance of the storage manager
    storage = None

    #: Storage for all of our factories.
    factories = {}

    #: Storage for all of the protocol configs.
    configs = {}

    #: The main configuration is stored here.
    main_config = None

    #: Storage of /all/ of the plugins, loaded or not.
    all_plugins = {}

    #: Storage of all of the loaded plugins.
    loaded_plugins = {}

    #: Storage of every plugin that depends on another plugin.
    plugins_with_dependencies = {}

    #: Whether the manager is already running or not
    running = False

    def __init__(self):
        # Set up the logger

        signal.signal(signal.SIGINT, self.signal_callback)

        self.logger = getLogger("Manager")
        self.storage = StorageManager()
        self.main_config = self.storage.get_file(self, "config", YAML,
                                                 "settings.yml")

        self.commands = CommandManager()
        self.commands.set_factory_manager(self)

        self.event_manager = EventManager()

        self.plugman = YamlPluginManagerSingleton()
        self.plugman.setPluginPlaces(["plugins"])
        self.plugman.setPluginInfoExtension("plug")

        self.load_config()  # Load the configuration
        self.collect_plugins()  # Collect the plugins
        self.load_plugins()  # Load the configured plugins
        self.load_protocols()  # Load and set up the protocols

        if not len(self.factories):
            self.logger.info(_("It seems like no protocols are loaded. "
                               "Shutting down.."))
            return

        try:
            self.metrics = Metrics(self.main_config, self)
        except Exception:
            self.logger.exception(_("Error setting up metrics."))

        event = ReactorStartedEvent(self)

        reactor.callLater(0, self.event_manager.run_callback,
                          "ReactorStarted", event)

    def run(self):
        if not self.running:
            self.running = True
            reactor.run()
        else:
            raise RuntimeError(_("Manager is already running!"))

    def signal_callback(self, signum, frame):
        try:
            try:
                self.unload()
            except Exception:
                self.logger.exception(_("Error while unloading!"))
                try:
                    reactor.stop()
                except Exception:
                    try:
                        reactor.crash()
                    except Exception:
                        pass
        except Exception:
            exit(0)

    # Load stuff

    def load_config(self):
        """
        Load the main configuration file.

        :return: Whether the config was loaded or not
        :rtype: bool
        """

        try:
            self.logger.info(_("Loading global configuration.."))
            if not self.main_config.exists:
                self.logger.error(_(
                    "Main configuration not found! Please correct this and try"
                    " again."))
                return False
        except IOError:
            self.logger.error(_(
                "Unable to load main configuration at config/settings.yml"))
            self.logger.error(_("Please check that this file exists."))
            return False
        except Exception:
            self.logger.error(_(
                "Unable to load main configuration at config/settings.yml"))
            output_exception(self.logger, logging.ERROR)
            return False
        return True

    def load_plugins(self):
        """
        Attempt to load all of the plugins.
        """

        self.logger.info(_("Loading plugins.."))

        self.logger.debug(_("Configured plugins: %s")
                          % ", ".join(self.main_config["plugins"]))

        self.logger.debug(_("Collecting plugins.."))

        if self.main_config["plugins"]:
            todo = []
            for info in self.plugman.getAllPlugins():
                name = info.name
                if info.dependencies:
                    self.plugins_with_dependencies[name] = info
                else:
                    todo.append(info)

            self.logger.debug(_("Loading plugins that have no dependencies "
                                "first."))

            for info in todo:
                name = info.name
                self.logger.debug(_("Checking if plugin '%s' is configured to "
                                    "load..") % name)
                if name in self.main_config["plugins"]:
                    self.logger.info(_("Attempting to load plugin: %s") % name)
                    result = self.load_plugin(name)
                    if result is not PLUGIN_LOADED:
                        if result is PLUGIN_LOAD_ERROR:
                            self.logger.warn(_("Error detected while loading "
                                               "plugin."))
                        elif result is PLUGIN_ALREADY_LOADED:
                            self.logger.warn(_("Plugin already loaded."))
                        elif result is PLUGIN_NOT_EXISTS:
                            self.logger.warn(_("Plugin doesn't exist."))
                        elif result is PLUGIN_DEPENDENCY_MISSING:
                            # THIS SHOULD NEVER HAPPEN!
                            self.logger.warn(_("Plugin dependency is "
                                               "missing."))

            self.logger.debug(_("Loading plugins that have dependencies."))

            for name, info in self.plugins_with_dependencies.items():
                self.logger.debug(_("Checking if plugin '%s' is configured to "
                                    "load..") % name)
                if name in self.main_config["plugins"]:
                    self.logger.info(_("Attempting to load plugin: %s") % name)
                    try:
                        result = self.load_plugin(name)
                    except RuntimeError as e:
                        message = e.message
                        if message == "maximum recursion depth exceeded " \
                                      "while calling a Python object":
                            self.logger.error(_("Dependency loop detected "
                                                "while loading: %s") % name)
                            self.logger.error(_("This plugin will not be "
                                                "available."))
                        elif message == "maximum recursion depth exceeded":
                            self.logger.error(_("Dependency loop detected "
                                                "while loading: %s") % name)
                            self.logger.error(_("This plugin will not be "
                                                "available."))
                        else:
                            raise e
                    except Exception as e:
                        raise e
                    if result is not PLUGIN_LOADED:
                        if result is PLUGIN_LOAD_ERROR:
                            self.logger.warn(_("Error detected while loading "
                                               "plugin."))
                        elif result is PLUGIN_ALREADY_LOADED:
                            self.logger.warn(_("Plugin already loaded."))
                        elif result is PLUGIN_NOT_EXISTS:
                            self.logger.warn(_("Plugin doesn't exist."))
                        elif result is PLUGIN_DEPENDENCY_MISSING:
                            self.logger.warn(_("Plugin dependency is "
                                               "missing."))
            event = PluginsLoadedEvent(self, self.loaded_plugins)
            self.event_manager.run_callback("PluginsLoaded", event)
        else:
            self.logger.info(_("No plugins are configured to load."))

    def load_plugin(self, name, unload=False):
        """
        Load a single plugin by name. This can return one of the following,
        from system.constants:

        * PLUGIN_ALREADY_LOADED
        * PLUGIN_DEPENDENCY_MISSING
        * PLUGIN_LOAD_ERROR
        * PLUGIN_LOADED
        * PLUGIN_NOT_EXISTS

        :param name: The plugin to load.
        :type name: str

        :param unload: Whether to unload the plugin, if it's already loaded.
        :type unload: bool
        """

        if name in self.all_plugins:
            if name in self.loaded_plugins:
                if unload:
                    res = self.unload_plugin(name)
                    if res != PLUGIN_UNLOADED:
                        return res
                else:
                    return PLUGIN_ALREADY_LOADED

            info = self.plugman.getPluginByName(name)
            if info.dependencies:
                depends = info.dependencies
                self.logger.debug(_("Dependencies for %s: %s") % (name,
                                                                  depends))
                for d_name in depends:
                    if d_name not in self.all_plugins:
                        self.logger.error(_("Error loading plugin %s: the"
                                            " plugin relies on another plugin "
                                            "(%s), but it is not present.")
                                          % (name, d_name))
                        return PLUGIN_DEPENDENCY_MISSING
                for d_name in depends:
                    result = self.load_plugin(d_name)
                    if result is not PLUGIN_LOADED:
                        if result is PLUGIN_ALREADY_LOADED:
                            continue

                        self.logger.warn(_("Unable to load dependency: %s")
                                         % d_name)
                        return result

            try:
                self.plugman.activatePluginByName(info.name)
                self.logger.debug(_("Loading plugin: %s")
                                  % info.plugin_object)
                self.logger.debug(_("Location: %s") % inspect.getfile
                                  (info.plugin_object.__class__))
                info.plugin_object.add_variables(info, self)
                info.plugin_object.logger = getLogger(name)
                self.logger.debug(_("Running setup method.."))
                info.plugin_object.setup()
            except Exception:
                self.logger.exception(_("Unable to load plugin: %s v%s")
                                      % (name, info.version))
                self.plugman.deactivatePluginByName(name)
                return PLUGIN_LOAD_ERROR
            else:
                self.loaded_plugins[name] = info
                self.logger.info(_("Loaded plugin: %s v%s")
                                 % (name, info.version))
                if info.copyright:
                    self.logger.info(_("Licensing: %s") % info.copyright)
                return PLUGIN_LOADED
        return PLUGIN_NOT_EXISTS

    def collect_plugins(self):
        """
        Collect all possible plugin candidates.

        If you're calling this, you should unload all of the plugins
        first.
        """

        self.all_plugins = {}
        self.plugman.collectPlugins()
        for info in self.plugman.getAllPlugins():
            self.all_plugins[info.name] = info

    def load_protocols(self):
        """
        Load and set up all of the configured protocols.
        """

        self.logger.info(_("Setting up protocols.."))

        for protocol in self.main_config["protocols"]:
            self.logger.info(_("Setting up protocol: %s") % protocol)
            conf_location = "protocols/%s.yml" % protocol
            result = self.load_protocol(protocol, conf_location)

            if result is not PROTOCOL_LOADED:
                if result is PROTOCOL_ALREADY_LOADED:
                    self.logger.warn(_("Protocol is already loaded."))
                elif result is PROTOCOL_CONFIG_NOT_EXISTS:
                    self.logger.warn(_("Unable to find protocol "
                                       "configuration."))
                elif result is PROTOCOL_LOAD_ERROR:
                    self.logger.warn(_("Error detected while loading "
                                       "protocol."))
                elif result is PROTOCOL_SETUP_ERROR:
                    self.logger.warn(_("Error detected while setting up "
                                       "protocol."))

    def load_protocol(self, name, conf_location):
        """
        Attempt to load a protocol by name. This can return one of the
        following, from system.constants:

        * PROTOCOL_ALREADY_LOADED
        * PROTOCOL_CONFIG_NOT_EXISTS
        * PROTOCOL_LOAD_ERROR
        * PROTOCOL_LOADED
        * PROTOCOL_SETUP_ERROR

        :param name: The name of the protocol
        :type name: str

        :param conf_location: The location of the config file, relative
            to the config/ directory, or a Config object
        :type conf_location: str, Config
        """

        if name in self.factories:
            return PROTOCOL_ALREADY_LOADED

        config = conf_location
        if not isinstance(conf_location, Config):
            # TODO: Prevent upward directory traversal properly
            conf_location = conf_location.replace("..", "")
            try:
                config = self.storage.get_file(self, "config", YAML,
                                               conf_location)
                if not config.exists:
                    return PROTOCOL_CONFIG_NOT_EXISTS
            except Exception:
                self.logger.error(
                    _("Unable to load configuration for the '%s' protocol.")
                    % name)
                output_exception(self.logger, logging.ERROR)
                return PROTOCOL_LOAD_ERROR
        try:
            self.factories[name] = Factory(name, config, self)
            self.factories[name].setup()
            return PROTOCOL_LOADED
        except Exception:
            if name in self.factories:
                del self.factories[name]
            self.logger.error(
                _("Unable to create factory for the '%s' protocol!")
                % name)
            output_exception(self.logger, logging.ERROR)
            return PROTOCOL_SETUP_ERROR

    # Unload stuff

    def unload_plugin(self, name):
        """
        Attempt to unload a plugin by name. This can return one of the
        following, from system.constants:

        * PLUGIN_NOT_EXISTS
        * PLUGIN_UNLOADED

        :param name: The name of the plugin
        :type name: str
        """

        if name in self.loaded_plugins:
            plug = self.plugman.getPluginByName(name).plugin_object
            self.commands.unregister_commands_for_owner(plug)
            try:
                self.plugman.deactivatePluginByName(name)
            except Exception:
                self.logger.error(_("Error disabling plugin: %s") % name)
                output_exception(self.logger, logging.ERROR)
            self.event_manager.remove_callbacks_for_plugin(name)
            self.storage.release_files(plug)
            del self.loaded_plugins[name]
            return PLUGIN_UNLOADED
        return PLUGIN_NOT_EXISTS

    def unload_protocol(self, name):  # Removes with a shutdown
        """
        Attempt to unload a protocol by name. This will also shut it down.

        :param name: The name of the protocol
        :type name: str

        :return: Whether the protocol was unloaded
        :rtype: bool
        """

        if name in self.factories:
            proto = self.factories[name]
            try:
                proto.shutdown()
            except Exception:
                self.logger.exception(_("Error shutting down protocol %s")
                                      % name)
            finally:
                try:
                    self.storage.release_file(self, "config",
                                              "protocols/%s.yml" % name)
                    self.storage.release_files(proto)
                    self.storage.release_files(proto.protocol)
                except Exception:
                    self.logger.exception("Error releasing files for protocol "
                                          "%s" % name)
            del self.factories[name]
            return True
        return False

    def unload(self):
        """
        Shut down and unload everything.
        """

        # Shut down!
        for name in self.factories.keys():
            self.logger.info(_("Unloading protocol: %s") % name)
            self.unload_protocol(name)
        for name in self.loaded_plugins.keys():
            self.logger.info(_("Unloading plugin: %s") % name)
            self.unload_plugin(name)

        if reactor.running:
            try:
                reactor.stop()
            except Exception:
                self.logger.exception("Error stopping reactor")

    # Grab stuff

    def get_protocol(self, name):
        """
        Get the instance of a protocol, by name.

        :param name: The name of the protocol
        :type name: str

        :return: The protocol, or None if it doesn't exist.
        """

        if name in self.factories:
            return self.factories[name].protocol
        return None

    def get_factory(self, name):
        """
        Get the instance of a protocol's factory, by name.

        :param name: The name of the protocol
        :type name: str

        :return: The factory, or None if it doesn't exist.
        """

        if name in self.factories:
            return self.factories[name]
        return None

    def get_plugin(self, name):
        """
        Get the insatnce of a plugin, by name.
        :param name: The name of the plugin
        :type name: str

        :return: The plugin, or None if it isn't loaded.
        """

        plug = self.plugman.getPluginByName(name)
        if plug:
            return plug.plugin_object
        return plug

    def remove_protocol(self, protocol):  # Removes without shutdown
        """
        Remove a protocol without shutting it down. You shouldn't use this.

        :param name: The name of the protocol
        :type name: str

        :return: Whether the protocol was removed.
        :rtype: bool
        """

        if protocol in self.factories:
            del self.factories[protocol]
            return True
        return False
