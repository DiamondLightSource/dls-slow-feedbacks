""" logconfig

This is essentially a template which can be copied into a python project and
used to easily achieve a good practice of logging. Modify the local copy as per
the project or site requirements.
"""

import getpass
import json
import logging
import logging.config
import os
import os.path
import threading

GELFLOG_SERVER = "graylog-log-target.diamond.ac.uk"
GELFLOG_SERVER_PORT = "12228"

default_config = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "%(levelname)s (%(filename)s) %(message)s"},
        "extended": {
            "format": "%(asctime)s - %(filename)24s:%(lineno)d - %(name)24s - %(levelname)6s - %(message)s"
        },
        "json": {
            "format": "name: %(name)s, level: %(levelname)s, time: %(asctime)s, message: %(message)s"
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": "DEBUG",
            "formatter": "simple",
            "stream": "ext://sys.stdout",
        },
        "stderr": {
            "class": "logging.StreamHandler",
            "level": "DEBUG",
            "formatter": "simple",
            "stream": "ext://sys.stderr",
        },
        "graylog_gelf": {
            "class": "pygelf.GelfTcpHandler",
            "level": "INFO",
            # A DLS-specific configuration: the graylog server address and port
            # Graylog2 cluster. Input: "Load-Balanced GELF TCP"
            "host": GELFLOG_SERVER,
            "port": int(GELFLOG_SERVER_PORT),
            "debug": True,
            #  The following custom fields will be disabled if setting this False
            "include_extra_fields": True,
            "username": getpass.getuser(),
            "pid": os.getpid(),
            "package": __package__,
        },
    },
    "loggers": {
        # Fine-grained logging configuration for individual modules or classes
        # Use this to set different log levels without changing 'real' code.
        "dls_slow_feedbacks": {
            # To enable debug during runtime, run this in the ioc console:
            # >>> logging.getLogger("dls_slow_feedbacks").setLevel(logging.DEBUG)
            "level": "INFO",
            "propagate": True,
            # As this is a continually running IOC, we dont have a
            # useful output (one that can be piped). Only user messages.
            # Hence, we default everything to stderr.
            "handlers": ["stderr"],
        },
    },
    "root": {
        # Set the level here to be the default minimum level of log record to be produced
        # If you set a handler to level DEBUG you will need to set either this level, or
        # the level of one of the loggers above to DEBUG or you won't see any DEBUG messages
        "level": "INFO",
        "handlers": ["graylog_gelf"],
        # "handlers": ["console"],
    },
}


class ThreadContextFilter(logging.Filter):
    """A logging context filter to add thread name and ID."""

    def filter(self, record):
        record.thread_id = str(threading.current_thread().ident)
        record.thread_name = str(threading.current_thread().name)
        return True


def setup_logging(
    default_log_config=None,
    default_level=logging.INFO,
    env_key="SLOW_FEEDBACKS_LOG_CFG",
    application=None,
):
    """Setup logging configuration

    Call this only once from the application main() function or __main__ module!

    This will configure the python logging module based on a logging configuration
    in the following order of priority:

       1. Log configuration file found in the environment variable specified in the `env_key` argument.
       2. Log configuration file found in the `default_log_config` argument.
       3. Default log configuration found in the `logconfig.default_config` dict.
       4. If all of the above fails: basicConfig is called with the `default_level` argument.

    Args:
        default_log_config (Optional[str]): Path to log configuration file.
        env_key (Optional[str]): Environment variable that can optionally contain
            a path to a configuration file.
        default_level (int): Logging level to set as default. Ignored if a log
            configuration is found elsewhere.
        application (str): Application name for Graylog.

    Returns: None
    """
    dict_config = default_config
    logconfig_filename = default_log_config
    env_var_value = os.getenv(env_key, None)

    if env_var_value is not None:
        logconfig_filename = env_var_value

    if logconfig_filename is not None and os.path.exists(logconfig_filename):
        with open(logconfig_filename, "rt") as f:
            file_config = json.load(f)
        if file_config is not None:
            dict_config = file_config

    if application is not None:
        try:
            dict_config["handlers"]["graylog_gelf"].update(
                {"application": str(application)}
            )
        except KeyError:
            print("Warning: No graylog_gelf handler found in the logging configuration. "
                  "Application name will not be set in the logs.")
    
    logging.config.dictConfig(dict_config)
