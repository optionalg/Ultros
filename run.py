# coding=utf-8

import sys
from kitchen.text.converters import getwriter

from utils.log import getLogger, open_log, close_log
from utils.misc import output_exception
from system.factory_manager import Manager

sys.stdout = getwriter('utf-8')(sys.stdout)
sys.stderr = getwriter('utf-8')(sys.stderr)

open_log("output.log")

logger = getLogger("System")

logger.info("Starting up..")

try:
    manager = Manager()

except Exception:
    logger.critical("Runtime error - process cannot continue!")
    output_exception(logger)

finally:
    close_log("output.log")
    try:
        raw_input("Press enter to exit.")
    except:
        pass
