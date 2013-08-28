"""
Responsible for reading in configuration files, validating the proper
format and providing sane defaults for parts that don't have any.

"""
import logging
from os import path
import platform
import yaml

(major, minor, rev) = platform.python_version_tuple()
if float('%s.%s' % (major, minor)) < 2.7:
    import logutils.dictconfig as logging_config
else:
    from logging import config as logging_config

from helper import NullHandler

LOGGER = logging.getLogger(__name__)


class Config(object):
    """The Config object holds the current state of the configuration for an
    application. If no configuration file is provided, it will used a set of
    defaults with very basic behavior for logging and daemonization.

    """
    APPLICATION = {'wake_interval': 60}
    DAEMON = {'user': None,
              'group': None,
              'pidfile': None,
              'prevent_core': True}
    LOGGING_FORMAT = ('%(levelname) -10s %(asctime)s %(process)-6d '
                      '%(processName) -20s %(threadName)-12s %(name) -30s '
                      '%(funcName) -25s L%(lineno)-6d: %(message)s')
    LOGGING = {'disable_existing_loggers': True,
               'filters': dict(),
               'formatters': {'verbose': {'datefmt': '%Y-%m-%d %H:%M:%S',
                                          'format': LOGGING_FORMAT}},
               'handlers': {'console': {'class': 'logging.StreamHandler',
                                        'debug_only': True,
                                        'formatter': 'verbose'}},
               'incremental': False,
               'loggers': {'helper': {'handlers': ['console'],
                                      'level': 'INFO',
                                      'propagate': True}},
               'root': {'handlers': [],
                        'level': logging.CRITICAL,
                        'propagate': True},
               'version': 1}

    def __init__(self, file_path=None):
        """Create a new instance of the configuration object, passing in the
        path to the configuration file.

        :param str file_path:

        """
        self.application = Data()
        self.daemon = Data()
        self._file_path = None
        self._values = Data()
        if file_path:
            self._file_path = self._validate(file_path)
            self._values = self._load_config_file()
        self._assign_defaults()

    def _assign_defaults(self):
        if 'Application' in self._values:
            self.application = Data(self._values['Application'])
        else:
            self.application = Data(self.APPLICATION)

        if 'Daemon' in self._values:
            self.daemon = Data(self._values['Daemon'])
        else:
            self.daemon = Data(self.DAEMON)

    def get(self, name, default=None):
        """Return the value for key if key is in the configuration, else default.

        :param str name: The key name to return
        :param mixed default: The default value for the key
        :return: mixed

        """
        return self._values.get(name, default)

    @property
    def logging(self):
        """Return the logging configuration in the form of a dictionary.

        :rtype: dict

        """
        config = self.LOGGING
        config_in = self._values.get('Logging', dict())
        for section in ['formatters', 'handlers', 'loggers', 'filters']:
            if section in config_in:
                for key in config_in[section]:
                    config[section][key] = config_in[section][key]
        LOGGER.debug(config)
        return config

    def reload(self):
        """Reload the configuration from disk returning True if the
        configuration has changed from the previous values.

        """
        if self._file_path:

            # Try and reload the configuration file from disk
            try:
                values = Data(self._load_config_file())
            except ValueError as error:
                LOGGER.error('Could not reload configuration: %s', error)
                return False

            # Only update the configuration if the values differ
            if hash(values) != hash(self._values):
                self._values = values
                self._assign_defaults()
                return True

        return False

    def _load_config_file(self):
        """Load the configuration file into memory, returning the content.

        """
        LOGGER.info('Loading configuration from %s', self._file_path)
        try:
            config = open(self._file_path).read()
        except OSError as error:
            raise ValueError('Could not read configuration file: %s' % error)
        try:
            return yaml.safe_load(config)
        except yaml.YAMLError as error:
            raise ValueError('Error in the configuration file: %s' % error)

    def _validate(self, file_path):
        """Normalize the path provided and ensure the file path, raising a
        ValueError if the file does not exist.

        :param str file_path:
        :return: str
        :raises: ValueError

        """
        file_path = path.abspath(file_path)
        if not path.exists(file_path):
            raise ValueError('Configuration file not found: %s' % file_path)
        return file_path


class LoggingConfig(object):
    """The Logging class is used for abstracting away dictConfig logging
    semantics and can be used by sub-processes to ensure consistent logging
    rule application.

    """
    DEBUG_ONLY = 'debug_only'
    HANDLERS = 'handlers'
    LOGGERS = 'loggers'

    def __init__(self, configuration, debug=None):
        """Create a new instance of the Logging object passing in the
        DictConfig syntax logging configuration and a debug flag.

        :param dict configuration: The logging configuration
        :param bool debug: Toggles use of debug_only loggers

        """
        # Force a NullLogger for some libraries that require it
        root_logger = logging.getLogger()
        root_logger.addHandler(NullHandler())

        self.config = configuration
        self.debug = debug
        self._configure()

    def update(self, configuration, debug=None):
        """Update the internal configuration values, removing debug_only
        handlers if debug is False. Returns True if the configuration has
        changed from previous configuration values.

        :param dict configuration: The logging configuration
        :param bool debug: Toggles use of debug_only loggers
        :rtype: bool

        """

        if hash(self.config) != hash(configuration) and debug != self.debug:
            self.config = configuration
            self.debug = debug
            self._configure()
            return True
        return False

    def _configure(self):
        """Configure the Python stdlib logger"""
        if self.debug is not None and not self.debug:
            self._remove_debug_handlers()
        self._remove_debug_only()
        logging_config.dictConfig(self.config)
        logging.captureWarnings(True)

    def _remove_debug_only(self):
        """Iterate through each handler removing the invalid dictConfig key of
        debug_only.

        """
        LOGGER.debug('Removing debug only from handlers')
        for handler in self.config[self.HANDLERS]:
            if self.DEBUG_ONLY in self.config[self.HANDLERS][handler]:
                del self.config[self.HANDLERS][handler][self.DEBUG_ONLY]

    def _remove_debug_handlers(self):
        """Remove any handlers with an attribute of debug_only that is True and
        remove the references to said handlers from any loggers that are
        referencing them.

        """
        remove = list()
        for handler in self.config[self.HANDLERS]:
            if self.config[self.HANDLERS][handler].get('debug_only'):
                remove.append(handler)
        for handler in remove:
            del self.config[self.HANDLERS][handler]

            for logger in self.config[self.LOGGERS].keys():
                logger = self.config[self.LOGGERS][logger]
                if handler in logger[self.HANDLERS]:
                    logger[self.HANDLERS].remove(handler)
        self._remove_debug_only()


class Data(object):
    """Data object configuration is wrapped in, can be used as a object with
    attributes or as a dict.

    """
    def __init__(self, value=None):
        super(Data, self).__init__()
        if value and isinstance(value, dict):
            for name in value.keys():
                if isinstance(value[name], dict):
                    object.__setattr__(self, name, Data(value[name]))
                else:
                    object.__setattr__(self, name, value[name])

    def __contains__(self, name):
        return name in self.__dict__.keys()

    def __delattr__(self, name):
        object.__delattr__(self, name)

    def __delitem__(self, name):
        if not name in self.__dict__:
            raise KeyError(name)
        object.__delattr__(self, name)

    def __getattribute__(self, name):
        return object.__getattribute__(self, name)

    def __getitem__(self, name):
        return object.__getattribute__(self, name)

    def __setitem__(self, name, value):
        if isinstance(value, dict) and name != '__dict__':
            value = Data(value)
        object.__setattr__(self, name, value)

    def __setattr__(self, name, value):
        if isinstance(value, dict) and name != '__dict__':
            value = Data(value)
        object.__setattr__(self, name, value)

    def __repr__(self):
        return repr(self.__dict__)

    def __len__(self):
        return len(self.__dict__.keys())

    def __iter__(self):
        for name in self.__dict__.keys():
            yield name

    def str(self):
        """Return a string representation of the data object.

        :rtype: str

        """
        return str(self.__dict__)

    def dict(self):
        """Return the data object as a dictionary.

        :rtype: dict

        """
        return dict(self.__dict__)

    def get(self, name, default=None):
        """Return the value for key if key is in the dictionary, else default.
        If default is not given, it defaults to None, so that this method
        never raises a KeyError.

        :param str name: The key name to return
        :param mixed default: The default value for the key
        :return: mixed

        """
        return self.__dict__.get(name, default)

    def has_key(self, name):
        """Test for the presence of key in the data object. has_key() is
        deprecated in favor of key in d.

        :param name:
        :return: bool

        """
        return name in self.__dict__

    def items(self):
        """Return a copy of the dictionary's list of (key, value) pairs.

        :rtype: list

        """
        return self.__dict__.items()

    def iteritems(self):
        """Return an iterator over the data keys. See the note for
        Data.items().

        Using itervalues() while adding or deleting entries in the data object
        may raise a RuntimeError or fail to iterate over all entries.

        :rtype: iterator
        :raises: RuntimeError

        """
        return self.__dict__.iteritems()

    def itervalues(self):
        """Return an iterator over the data values. See the note for
        Data.items().

        Using itervalues() while adding or deleting entries in the data object
        may raise a RuntimeError or fail to iterate over all entries.

        :rtype: iterator
        :raises: RuntimeError

        """
        return self.__dict__.itervalues()

    def keys(self):
        """Return a copy of the dictionary's list of keys. See the note for
        Data.items()

        :rtype: list

        """
        return self.__dict__.keys()

    def pop(self, name, default=None):
        """If key is in the dictionary, remove it and return its value, else
        return default. If default is not given and key is not in the
        dictionary, a KeyError is raised.

        :param str name: The key name
        :param mixed default: The default value
        :raises: KeyError

        """
        return self.__dict__.pop(name, default)

    def setdefault(self, name, default=None):
        """If key is in the dictionary, return its value. If not, insert key
        with a value of default and return default. default defaults to None.

        :param str name: The key
        :param mixed default: The value
        :return: mixed

        """
        self.__dict__.setdefault(name, default)

    def update(self, other=None, **kwargs):
        """Update the dictionary with the key/value pairs from other,
        overwriting existing keys. update() accepts either another dictionary
        object or an iterable of key/value pairs (as tuples or other iterables
        of length two). If keyword arguments are specified, the dictionary is
        then updated with those key/value pairs: d.update(red=1, blue=2).

        :param dict other: Dict or other iterable
        :param dict **kwargs: Key/value pairs to update
        :rtype: None

        """
        self.__dict__.update(other, **kwargs)

    def values(self):
        """Return the configuration values

        :rtype: list

        """
        return self.__dict__.values()
