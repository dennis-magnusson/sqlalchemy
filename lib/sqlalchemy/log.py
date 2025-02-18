# log.py
# Copyright (C) 2006-2025 the SQLAlchemy authors and contributors
# <see AUTHORS file>
# Includes alterations by Vinay Sajip vinay_sajip@yahoo.co.uk
#
# This module is part of SQLAlchemy and is released under
# the MIT License: https://www.opensource.org/licenses/mit-license.php

"""Logging control and utilities.

Control of logging for SA can be performed from the regular python logging
module.  The regular dotted module namespace is used, starting at
'sqlalchemy'.  For class-level logging, the class name is appended.

The "echo" keyword parameter, available on SQLA :class:`_engine.Engine`
and :class:`_pool.Pool` objects, corresponds to a logger specific to that
instance only.

"""
from __future__ import annotations

import logging
import sys
from typing import Any
from typing import Optional
from typing import overload
from typing import Set
from typing import Type
from typing import TypeVar
from typing import Union

from .util import py311
from .util.typing import Literal


STACKLEVEL = True
# needed as of py3.11.0b1
# #8019
STACKLEVEL_OFFSET = 2 if py311 else 1

_IT = TypeVar("_IT", bound="Identified")

_EchoFlagType = Union[None, bool, Literal["debug"]]

# set initial level to WARN.  This so that
# log statements don't occur in the absence of explicit
# logging being enabled for 'sqlalchemy'.
rootlogger = logging.getLogger("sqlalchemy")
if rootlogger.level == logging.NOTSET:
    rootlogger.setLevel(logging.WARN)


def _add_default_handler(logger: logging.Logger) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(handler)


_logged_classes: Set[Type[Identified]] = set()


def _qual_logger_name_for_cls(cls: Type[Identified]) -> str:
    return (
        getattr(cls, "_sqla_logger_namespace", None)
        or cls.__module__ + "." + cls.__name__
    )


def class_logger(cls: Type[_IT]) -> Type[_IT]:
    logger = logging.getLogger(_qual_logger_name_for_cls(cls))
    cls._should_log_debug = lambda self: logger.isEnabledFor(  # type: ignore[method-assign]  # noqa: E501
        logging.DEBUG
    )
    cls._should_log_info = lambda self: logger.isEnabledFor(  # type: ignore[method-assign]  # noqa: E501
        logging.INFO
    )
    cls.logger = logger
    _logged_classes.add(cls)
    return cls


_IdentifiedLoggerType = Union[logging.Logger, "InstanceLogger"]


class Identified:
    __slots__ = ()

    logging_name: Optional[str] = None

    logger: _IdentifiedLoggerType

    _echo: _EchoFlagType

    def _should_log_debug(self) -> bool:
        return self.logger.isEnabledFor(logging.DEBUG)

    def _should_log_info(self) -> bool:
        return self.logger.isEnabledFor(logging.INFO)


class InstanceLogger:
    """A logger adapter (wrapper) for :class:`.Identified` subclasses.

    This allows multiple instances (e.g. Engine or Pool instances)
    to share a logger, but have its verbosity controlled on a
    per-instance basis.

    The basic functionality is to return a logging level
    which is based on an instance's echo setting.

    Default implementation is:

    'debug' -> logging.DEBUG
    True    -> logging.INFO
    False   -> Effective level of underlying logger (
    logging.WARNING by default)
    None    -> same as False
    """

    # Map echo settings to logger levels
    _echo_map = {
        None: logging.NOTSET,
        False: logging.NOTSET,
        True: logging.INFO,
        "debug": logging.DEBUG,
    }

    _echo: _EchoFlagType

    __slots__ = ("echo", "logger")

    def __init__(self, echo: _EchoFlagType, name: str):
        self.echo = echo
        self.logger = logging.getLogger(name)

        # if echo flag is enabled and no handlers,
        # add a handler to the list
        if self._echo_map[echo] <= logging.INFO and not self.logger.handlers:
            _add_default_handler(self.logger)

    #
    # Boilerplate convenience methods
    #
    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Delegate a debug call to the underlying logger."""

        self.log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Delegate an info call to the underlying logger."""

        self.log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Delegate a warning call to the underlying logger."""

        self.log(logging.WARNING, msg, *args, **kwargs)

    warn = warning

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """
        Delegate an error call to the underlying logger.
        """
        self.log(logging.ERROR, msg, *args, **kwargs)

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Delegate an exception call to the underlying logger."""

        kwargs["exc_info"] = 1
        self.log(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Delegate a critical call to the underlying logger."""

        self.log(logging.CRITICAL, msg, *args, **kwargs)

    def log(self, level: int, msg: str, *args: Any, **kwargs: Any) -> None:
        """Delegate a log call to the underlying logger.

        The level here is determined by the echo
        flag as well as that of the underlying logger, and
        logger._log() is called directly.

        """

        # inline the logic from isEnabledFor(),
        # getEffectiveLevel(), to avoid overhead.

        if self.logger.manager.disable >= level:
            return

        selected_level = self._echo_map[self.echo]
        if selected_level == logging.NOTSET:
            selected_level = self.logger.getEffectiveLevel()

        if level >= selected_level:
            if STACKLEVEL:
                kwargs["stacklevel"] = (
                    kwargs.get("stacklevel", 1) + STACKLEVEL_OFFSET
                )

            self.logger._log(level, msg, args, **kwargs)

    def isEnabledFor(self, level: int) -> bool:
        """Is this logger enabled for level 'level'?"""

        if self.logger.manager.disable >= level:
            return False
        return level >= self.getEffectiveLevel()

    def getEffectiveLevel(self) -> int:
        """What's the effective level for this logger?"""

        level = self._echo_map[self.echo]
        if level == logging.NOTSET:
            level = self.logger.getEffectiveLevel()
        return level


def instance_logger(
    instance: Identified, echoflag: _EchoFlagType = None
) -> None:
    """create a logger for an instance that implements :class:`.Identified`."""

    if instance.logging_name:
        name = "%s.%s" % (
            _qual_logger_name_for_cls(instance.__class__),
            instance.logging_name,
        )
    else:
        name = _qual_logger_name_for_cls(instance.__class__)

    instance._echo = echoflag  # type: ignore

    logger: Union[logging.Logger, InstanceLogger]

    if echoflag in (False, None):
        # if no echo setting or False, return a Logger directly,
        # avoiding overhead of filtering
        logger = logging.getLogger(name)
    else:
        # if a specified echo flag, return an EchoLogger,
        # which checks the flag, overrides normal log
        # levels by calling logger._log()
        logger = InstanceLogger(echoflag, name)

    instance.logger = logger  # type: ignore


class echo_property:
    __doc__ = """\
    When ``True``, enable log output for this element.

    This has the effect of setting the Python logging level for the namespace
    of this element's class and object reference.  A value of boolean ``True``
    indicates that the loglevel ``logging.INFO`` will be set for the logger,
    whereas the string value ``debug`` will set the loglevel to
    ``logging.DEBUG``.
    """

    @overload
    def __get__(
        self, instance: Literal[None], owner: Type[Identified]
    ) -> echo_property: ...

    @overload
    def __get__(
        self, instance: Identified, owner: Type[Identified]
    ) -> _EchoFlagType: ...

    def __get__(
        self, instance: Optional[Identified], owner: Type[Identified]
    ) -> Union[echo_property, _EchoFlagType]:
        if instance is None:
            return self
        else:
            return instance._echo

    def __set__(self, instance: Identified, value: _EchoFlagType) -> None:
        instance_logger(instance, echoflag=value)
