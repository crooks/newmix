#!/usr/bin/python
#
# vim: tabstop=4 expandtab shiftwidth=4 noautoindent
#
# nymserv.py - A Basic Nymserver for delivering messages to a shared mailbox
# such as alt.anonymous.messages.
#
# Copyright (C) 2012 Steve Crook <steve@mixmin.net>
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
#
# You should have received a copy of the GNU General Public License along with
# this program.  If not, see <http://www.gnu.org/licenses/>.

import argparse
import sys
import logging
import os.path
import requests
from Config import config
import mix
import Pool
import timing
from daemon import Daemon


class Server(Daemon):
    def run(self):
        # Loop until a SIGTERM or Ctrl-C is received.
        while True:
            # Process outbound messages first.  This ensures that no message
            # is received, processed and sent during the same iteration.  Not
            # sure if doing so would be a bad thing for anonymity but not
            # doing is it very unlikely to be bad.
            if out_pool.trigger():
                process_outbound()
            process_inbound()
            # Some consideration should probably given to pool trigger times
            # rather than stubbornly looping every minute.
            timing.sleep(60)


def process_inbound():
    """
    Messages from other remailers are stored in the inbound pool.  These are
    periodically processed and written to the outbound pool.  The exception to
    this rule is when we are the final hop in a remailer chain.  In this
    instance the message is delivered and not outbound queued.
    """
    generator = in_pool.select_all()
    for filename in generator:
        with open(filename, 'r') as f:
            try:
                packet_data = m.packet_read(f.read())
            except ValveError, e:
                # ValueError is returned when the packet being processed isn't
                # compliant with the specification.  These messages are
                # deleted without further consideration.
                log.debug("Newmix packet read failed with: %s", e)
                in_pool.delete(filename)
                continue
            # Process the Base64 component of the message.
            m.decode(packet_data['binary'])
            in_pool.delete(filename)
            if m.is_exit:
                #TODO Actually do something with exit messages
                log.info("We got an exit message!!")


def process_outbound():
    """
    Outbound messages are stored in a queue and a random subset of that queue
    is processed each time this function is called (providing there are
    sufficient messages queued to trigger sending.  No processing has to
    be done prior to transmission.  This happens as part of the inbound queue
    processing.
    """
    generator = out_pool.select_subset()
    for filename in generator:
        with open(filename, 'r') as f:
            try:
                packet_data = m.packet_read(f.read())
            except ValveError, e:
                log.debug("Newmix packet read failed with: %s", e)
                out_pool.delete(filename)
                continue
        if packet_data['expire'] < timing.epoch_days():
            # Remailers come and go.  They also fail from time to time.  When
            # a message is written to the outbound queue, it's stamped with an
            # expiry date.  If it's still queued after that date, we give up
            # trying to send it.  Sadly, a message is lost but messages can't
            # be queued forever.
            log.warn("Giving up on sending msg to %s.",
                     packet_data['next_hop'])
            #TODO Statistically mark down this remailer.
            out_pool.delete(filename)
            continue
        payload = {'newmix': packet_data['packet']}
        try:
            # Actually try to send the message to the next_hop.  There are
            # probably a lot of failure conditions to handle at this point.
            r = requests.post('http://%s/cgi-bin/webcgi.py'
                              % packet_data['next_hop'],
                              data=payload)
            if r.status_code == requests.codes.ok:
                out_pool.delete(filename)
        except requests.exceptions.ConnectionError:
            #TODO Mark down remailer statistics.
            log.info("Unable to connect to %s", packet_data['next_hop'])


log = logging.getLogger("newmix.%s" % __name__)
if (__name__ == "__main__"):
    logfmt = config.get('logging', 'format')
    datefmt = config.get('logging', 'datefmt')
    loglevels = {'debug': logging.DEBUG, 'info': logging.INFO,
                 'warn': logging.WARN, 'error': logging.ERROR}
    log = logging.getLogger("newmix")
    log.setLevel(loglevels[config.get('logging', 'level')])
    filename = os.path.join(config.get('logging', 'path'), 'newmix.log')
    handler = logging.StreamHandler()
    #handler = logging.FileHandler(filename, mode='a')
    handler.setFormatter(logging.Formatter(fmt=logfmt, datefmt=datefmt))
    log.addHandler(handler)

    m = mix.Message()
    # The inbound pool always processes every message.
    in_pool = Pool.Pool(name='inpool',
                        pooldir=config.get('pool', 'indir'))
    out_pool = Pool.Pool(name='outpool',
                         pooldir=config.get('pool', 'outdir'),
                         interval=config.get('pool', 'interval'),
                         rate=config.getint('pool', 'rate'),
                         size=config.getint('pool', 'size'))
    s = Server(config.get('general', 'pidfile'),
               stderr='/home/crooks/newmix/log/err.log')

    # Handle command line args
    if len(sys.argv) >= 1:
        cmd = sys.argv[1]
        if cmd == "--start":
            s.start()
        elif cmd == "--stop":
            s.stop()
        elif cmd == "--run":
            s.run()
