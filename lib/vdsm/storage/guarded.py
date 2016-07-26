#
# Copyright 2016 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
#
# Refer to the README and COPYING files for full details of the license
#

from __future__ import absolute_import
import logging
import sys

import six

log = logging.getLogger('storage.guarded')


class ReleaseError(Exception):
    pass


class context(object):
    """
    A context manager to lock groups of storage entities for an operation.

    When performing an operation on storage (eg. copying data from one volume
    to another volume), the entities (volumes) must be locked to protect them
    from conflicting access by other threads of this application and (in the
    future) from simultaneous access by other hosts.  This requires the use of
    multiple layers of locks and rigid lock ordering rules to prevent deadlock.

    This class receives a variable number of lock lists corresponding to each
    entity involved in an operation.  The locks from all entities are grouped
    together and any duplicate locks removed.  Next, the locks are sorted by
    namespace and then by name.  When entering the context the locks are
    acquired in sorted order.  When exiting the context the locks are released
    in reverse order.  Errors are handled as gracefully as possible with any
    acquired locks being released in the proper order.
    """

    def __init__(self, locks):
        """
        Receives a variable number of locks which must descend from
        AbstractLock.  The locks are deduplicated and sorted.
        """
        self._locks = sorted(set(locks))
        self._held_locks = []

    def __enter__(self):
        for lock in self._locks:
            try:
                lock.acquire()
            except:
                exc = sys.exc_info()
                log.error("Error acquiring lock %r", lock)
                try:
                    self._release()
                except ReleaseError:
                    log.exception("Error releasing locks")
                try:
                    six.reraise(*exc)
                finally:
                    del exc

            self._held_locks.append(lock)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            self._release()
        except ReleaseError:
            if exc_type is None:
                raise
            # Don't hide the original error
            log.exception("Error releasing locks")
            return False

    def _release(self):
        errors = []
        while self._held_locks:
            lock = self._held_locks.pop()
            try:
                lock.release()
            except Exception as e:
                errors.append(e)
        if errors:
            raise ReleaseError(errors)


class AbstractLock(object):
    @property
    def ns(self):
        raise NotImplementedError

    @property
    def name(self):
        raise NotImplementedError

    @property
    def mode(self):
        raise NotImplementedError

    def acquire(self):
        raise NotImplementedError

    def release(self):
        raise NotImplementedError

    def __eq__(self, other):
        return self._key() == other._key()

    def __ne__(self, other):
        return not self == other

    def __lt__(self, other):
        return (self.ns, self.name) < (other.ns, other.name)

    def __hash__(self):
        return hash(self._key())

    def _key(self):
        return type(self), self.ns, self.name, self.mode
