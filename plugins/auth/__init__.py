__author__ = 'Gareth Coles'

import logging

import auth_handler
import permissions_handler

from system.command_manager import CommandManager
from system.plugin import Plugin
from utils.config import Config
from utils.data import Data
from utils.misc import output_exception


class AuthPlugin(Plugin):

    config = None
    passwords = None
    permissions = None

    auth_h = None
    perms_h = None

    def setup(self):
        try:
            self.config = Config("plugins/auth.yml")
        except Exception:
            self.logger.error("Error loading configuration!")
            output_exception(self.logger, logging.WARN)
            self.logger.error("Disabling..")
            self._disable_self()
            return
        if not self.config.exists:
            self.logger.error("Unable to find config/plugins/auth.yml")
            self.logger.error("Disabling..")
            self._disable_self()
            return

        self.commands = CommandManager.get()

        if self.config["use-auth"]:
            try:
                self.passwords = Data("plugins/auth/passwords.yml")
            except Exception:
                self.logger.error("Unable to load passwords. They will be"
                                  " unavailable!")
                output_exception(self.logger, logging.ERROR)
            else:
                self.auth_h = auth_handler.authHandler(self, self.passwords)
                result = self.commands.add_auth_handler(self.auth_h)
                if not result:
                    self.logger.warn("Unable to set auth handler!")

        if self.config["use-permissions"]:
            try:
                self.permissions = Data("plugins/auth/permissions.yml")
            except Exception:
                self.logger.error("Unable to load permissions. They will be"
                                  " unavailable!")
                output_exception(self.logger, logging.ERROR)
            else:
                self.perms_h = permissions_handler.permissionsHandler(
                    self, self.permissions)
                result = self.commands.set_permissions_handler(self.perms_h)
                if not result:
                    self.logger.warn("Unable to set permissions handler!")

    def deactivate(self):
        pass

    def _disable_self(self):
        self.factory_manager.plugman.deactivatePluginByName(self.info.name)