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

from Crypto.PublicKey import RSA
from Config import config
import hashlib
import os.path
import timing
import sqlite3
import sys
import logging
import http

class KeyImportError(Exception):
    pass

class Keystore(object):
    """
    """
    def __init__(self):
        log.info("Initializing Keystore")
        filename = "directory.db"
        log.debug("Opening database: %s", filename)
        self.conn = sqlite3.connect(filename)
        self.conn.text_factory = str
        self.cur = self.conn.cursor()
        self.cur.execute("""SELECT name FROM sqlite_master
                            WHERE type='table' AND name='keyring'""")
        if self.cur.fetchone() is None:
            self.create_keyring()
        # On startup, force a daily run
        self.daily_events(force=True)

    def create_keyring(self):
        log.info('Creating DB table "keyring"')
        self.cur.execute('''CREATE TABLE keyring
                            (keyid text, name text, address text,
                             pubkey text, seckey text,
                             validfr text, validto text, advertise int,
                             smtp int, UNIQUE (keyid))''')
        self.conn.commit()

    def generate(self):
        log.info("Generating new RSA keys")
        seckey = RSA.generate(config.getint('general', 'keylen'))
        pubkey = seckey.publickey()
        pubpem = pubkey.exportKey(format='PEM')
        keyid = hashlib.md5(pubpem).hexdigest()

        insert = (keyid,
                  config.get('general', 'name'),
                  config.get('general', 'address'),
                  pubpem,
                  seckey.exportKey(format='PEM'),
                  timing.today(),
                  timing.datestamp(timing.future(days=270)),
                  1,
                  config.getboolean('general', 'smtp'))
        self.cur.execute('''INSERT INTO keyring (keyid, name, address,
                                                 pubkey, seckey, validfr,
                                                 validto, advertise, smtp)
                            VALUES (?,?,?,?,?,?,?,?,?)''', insert)
        self.conn.commit()
        #self.test_load()
        return str(keyid)

    def test_load(self):
        seckey = RSA.generate(1024)
        pubkey = seckey.publickey()
        pubpem = pubkey.exportKey(format='PEM')
        keyid = hashlib.md5(pubpem).hexdigest()
        insert = (keyid,
                  'tester',
                  'www.mixmin.net',
                  pubpem,
                  seckey.exportKey(format='PEM'),
                  timing.today(),
                  timing.datestamp(timing.future(days=270)),
                  1,
                  0)
        self.cur.execute('''INSERT INTO keyring (keyid, name, address,
                                                 pubkey, seckey, validfr,
                                                 validto, advertise, smtp)
                            VALUES (?,?,?,?,?,?,?,?,?)''', insert)
        self.conn.commit()
        self.test_keyid = keyid

    def key_to_advertise(self):
        loop_count = 0
        data = None
        while data is None:
            self.cur.execute('''SELECT keyid,seckey FROM keyring
                                WHERE seckey IS NOT NULL
                                AND validfr <= datetime('now')
                                AND datetime('now') <= validto
                                AND advertise''')
            data = self.cur.fetchone()
            if data is None:
                if loop_count > 0:
                    raise KeystoreError("Unable to generate seckey")
                self.generate()
            loop_count += 1
        self.mykey = (data[0], RSA.importKey(data[1]))
        log.info("Advertising KeyID: %s", data[0])
        self.advertise()

    def daily_events(self, force=False):
        """
        Perform once per day events.
        """
        # Bypass daily events unless forced to run them or it's actually a
        # new day.
        if not force and self.daily_trigger == timing.epoch_days():
            return None
        if force:
            log.info("Forced run of daily housekeeping actions.")
        else:
            log.info("Running routine daily housekeeping actions.")

        # Stop advertising keys that expire in the next 28 days.
        plus28 = timing.timestamp(timing.future(days=28))
        self.cur.execute('''UPDATE keyring SET advertise=0
                            WHERE ?>validto AND advertise=1''', (plus28,))
        # Delete any keys that have expired.
        self.cur.execute('''DELETE FROM keyring
                            WHERE datetime('now') > validto''')
        self.conn.commit()

        # If any seckeys expired, it's likely a new key will be needed.  Check
        # what key should be advertised and advertise it.
        self.key_to_advertise()
        self.advertise()

        self.sec_cache = {}

        # This is a list of known remailer addresses.  It's referenced each
        # time this remailer functions as an Intermediate Hop.  The message
        # contains the address of the next_hop and this list confirms that
        # is a known remailer.
        self.cur.execute("""SELECT address FROM keyring WHERE advertise""")
        data = self.cur.fetchall()
        self.known_addresses = [c[0] for c in data]
        # Reset the fetch cache.  This cache prevents repeated http GET
        # requests being sent to dead or never there remailers.
        self.fetch_cache = []

        # Set the daily trigger to today's date.
        self.daily_trigger = timing.epoch_days()
        
    def xget_public(self, keyid):
        """
        Return the Public Key object associated with the keyid provided.  If
        no key is found, return None.
        """
        self.cur.execute("""SELECT pubkey FROM keyring
                             WHERE keyid=?""", (keyid,))
        keys = self.cur.fetchall()
        if len(keys) == 1:
            self.pubcache[keyid] = RSA.importKey(keys[0])
            return self.pubcache[keyid]
        else:
            return None

    def get_public(self, address):
        """ Public keys are only used during encoding operations (client mode
            and random hops).  Performance is not important so no caching is
            performed.  The KeyID is required as it's encoded in the message
            so the recipient remailer knows which key to use for decryption.
        """
        self.cur.execute("""SELECT keyid,pubkey FROM keyring
                             WHERE address=? AND advertise""", (address,))
        data = self.cur.fetchone()
        if data is None or data[0] is None or data[1] is None:
            raise KeystoreError("%s: No public key" % address)
        else:
            return data[0], RSA.importKey(data[1])

    def get_secret(self, keyid):
        """ Return the Secret Key object associated with the keyid provided.
            If no key is found, return None.
        """
        if keyid in self.sec_cache:
            log.debug("Seckey cache hit for %s", keyid)
            return self.sec_cache[keyid]
        log.debug("Seckey cache miss for %s", keyid)
        self.cur.execute("""SELECT seckey FROM keyring
                             WHERE keyid=?""", (keyid,))
        data = self.cur.fetchone()
        if data[0] is None:
            return None
        self.sec_cache[keyid] = RSA.importKey(data[0])
        log.debug("Got seckey from DB")
        return self.sec_cache[keyid]

    def advertise(self):
        self.cur.execute("""SELECT name,address,validfr,validto,smtp,
                                   pubkey
                            FROM keyring
                            WHERE keyid=?""", (self.mykey[0],))
        name, address, fr, to, smtp, pub = self.cur.fetchone()
        f = open("publish.txt", 'w')
        f.write("Name: %s\n" % name)
        f.write("Address: %s\n" % address)
        f.write("KeyID: %s\n" % self.mykey[0])
        f.write("Valid From: %s\n" % fr)
        f.write("Valid To: %s\n" % to)
        f.write("SMTP: %s\n" % smtp)
        f.write("\n%s\n\n" % pub)
        self.cur.execute("""SELECT address FROM keyring
                            WHERE keyid != ? AND advertise""",
                         (self.mykey[0],))
        addresses = self.cur.fetchall()
        f.write("Known remailers:-\n")
        for r in addresses:
            f.write("%s\n" % r)
        f.close()

    def conf_fetch(self, address):
        if address.startswith("http://"):
            log.warn('Address %s should not be prefixed with "http://"',
                     address)
            address = address[7:]
        # If the address is unknown, steps are taken to find out about it.
        if address in self.known_addresses:
            log.debug("Not fetching remailer-conf for %s, it's already "
                      "known.", address)
            return 0
        # Has there already been an attempt to retreive this address
        # today?
        if address in self.fetch_cache:
            log.info("Not trying to fetch remailer-conf for %s.  Already "
                     "attempted today", address)
            raise KeyImportError("URL retrieval already attempted today")
        self.fetch_cache.append(address)

        #TODO At this point, fetch a URL
        log.debug("Attempting to fetch remailer-conf for %s", address)
        conf_page = http.get("http://%s/remailer-conf.txt" % address)
        if conf_page is None:
            raise KeyImportError("Could not retreive remailer-conf for %s"
                                 % address)
        keys = {}
        for line in conf_page.split("\n"):
            if ": " in line:
                key, val = line.split(": ", 1)
                if key == "Valid From":
                    key = "validfr"
                elif key == "Valid To":
                    key = "validto"
                keys[key.lower()] = val
        b = conf_page.rfind("-----BEGIN PUBLIC KEY-----")
        e = conf_page.rfind("-----END PUBLIC KEY-----")
        if b >= 0 and e >= 0:
            keys['pubkey'] = conf_page[b:e + 24]
        else:
            # Can't import a remailer without a pubkey
            raise KeyImportError("Public key not found")
        try:
            test = RSA.importKey(keys['pubkey'])
        except ValueError:
            raise KeyImportError("Public key is not valid")

        # Date validation section
        try:
            if not 'validfr' in keys or not 'validto' in keys:
                raise KeyImportError("Validity period not defined")
            if timing.dateobj(keys['validfr']) > timing.now():
                raise KeyImportError("Key is not yet valid")
            if timing.dateobj(keys['validto']) < timing.now():
                raise KeyImportError("Key has expired")
        except ValueError:
            raise KeyImportError("Invalid date format")
        # The KeyID should always be the MD5 hash of the Pubkey.
        if 'keyid' not in keys:
            raise KeyImportError("KeyID not published")
        if keys['keyid'] != hashlib.md5(keys['pubkey']).hexdigest():
            print hashlib.md5(keys['pubkey']).hexdigest()
            raise KeyImportError("Key digest error")
        # Convert keys to an ordered tuple, ready for a DB insert.
        try:
            insert = (keys['name'],
                      keys['address'],
                      keys['keyid'],
                      keys['validfr'],
                      keys['validto'],
                      bool(keys['smtp']),
                      keys['pubkey'],
                      1)
        except KeyError:
            # We need all the above keys to perform a valid import
            raise KeyImportError("Import Tuple construction failed")
        self.cur.execute("""INSERT INTO keyring (name, address, keyid,
                                                 validfr, validto, smtp,
                                                 pubkey, advertise)
                            VALUES (?,?,?,?,?,?,?,?)""", insert)
        self.conn.commit()
        self.known_addresses.append(address)
        return keys['keyid'], keys['pubkey']


    def chain(self):
        return self.known_addresses[0]

        

log = logging.getLogger("newmix.%s" % __name__)
if (__name__ == "__main__"):
    log = logging.getLogger("Pymaster")
    log.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    log.addHandler(handler)
    ks = Keystore()
    #ks.conf_fetch("www.mixmin.net")
