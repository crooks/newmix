#!/usr/bin/python
#
# vim: tabstop=4 expandtab shiftwidth=4 autoindent
#
# timing.py - Some basic date/time functions
# Copyright (C) 2014 Steve Crook <steve@mixmin.net>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 3, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTIBILITY
# or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
# for more details.

import datetime
import time


def now():
    return datetime.datetime.utcnow()
    #return datetime.datetime.now()


def today():
    """Return a date object for today."""
    return now().date()


def future(days=0, hours=0, mins=0, secs=0):
    return now() + datetime.timedelta(days=days, hours=hours, minutes=mins,
                                      seconds=secs)


def past(days=0, hours=0, mins=0, secs=0):
    return now() - datetime.timedelta(days=days, hours=hours, minutes=mins,
                                      seconds=secs)

def date_future(days):
    return today() + datetime.timedelta(days=days)


def date_past(days):
    return today() - datetime.timedelta(days=days)


def dhms_future(timestr):
    """Take a string formatted as 00h and convert it to a time in the future.
    """
    period = int(timestr[0:-1])
    unit = timestr[-1].lower()
    if unit == "d":
        return future(days=period)
    elif unit == "h":
        return future(hours=period)
    elif unit == "m":
        return future(mins=period)
    elif unit == "s":
        return future(secs=period)
    raise ValueError("%s: Unknown time period char" % unit)


def dhms_secs(timestr):
    """Take a string formatted as 00h and convert it to seconds.
    """
    period = int(timestr[0:-1])
    unit = timestr[-1].lower()
    if unit == "d":
        return period * 24 * 60 * 60
    elif unit == "h":
        return period * 60 * 60
    elif unit == "m":
        return period * 60
    elif unit == "s":
        return period
    raise ValueError("%s: Unknown time period char" % unit)


def epoch_days():
    """Return the number of days since Epoch (1st Jan 1970).
    """
    return int(time.time() / 86400)


def timestamp(stamp):
    return stamp.strftime("%Y-%m-%d %H:%M:%S")


def msgidstamp():
    return now().strftime("%Y%m%d%H%M%S")


def datestamp(stamp):
    return stamp.strftime("%Y-%m-%d")


def dateobj(datestr):
    """
    Take a string formated date (yyyy-mm-dd) and return a date object.
    """
    return datetime.datetime.strptime(datestr, '%Y-%m-%d').date()


def nowstamp():
    """A shortcut function to return a textual representation of now."""
    return timestamp(now())


def last_midnight():
    return now().replace(hour=0, minute=0, second=0, microsecond=0)


def next_midnight():
    """Return a datetime object relating to the next midnight.

    """
    return last_midnight() + datetime.timedelta(days=1)


def sleep(n):
    time.sleep(n)


if (__name__ == "__main__"):
    print datestamp(future(days=365))
