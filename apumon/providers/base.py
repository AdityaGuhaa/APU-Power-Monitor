"""
APU-Power-Monitor - Sensor provider interface
Copyright (c) 2026 Aditya Guha
Licensed under the MIT License. See LICENSE file in the project root.

A provider is one way of reading APU telemetry on one platform. Implementations
must be cheap to construct (detection belongs in `is_available`) and must never
raise out of `read` - returning None is how a provider reports a transient
failure, which the monitor surfaces to the client as an error event.
"""

import platform


class SensorProvider:
    """Base class for all telemetry sources."""

    #: Short identifier used by APU_MONITOR_PROVIDER and shown in the UI.
    name = "base"
    #: One line shown in the startup banner and the dashboard footer.
    description = "abstract provider"
    #: Platforms this provider can run on, as returned by platform.system().
    #: An empty tuple means "any".
    platforms = ()
    #: Providers with richer data are probed first (higher wins).
    priority = 0

    def platform_matches(self):
        return not self.platforms or platform.system() in self.platforms

    def is_available(self):
        """
        True when this provider can read something useful right now.
        Must be side-effect free and reasonably fast (it runs at startup).
        """
        raise NotImplementedError

    def read(self):
        """Return a list of ApuSample, or None if the read failed."""
        raise NotImplementedError

    def close(self):
        """Release any long-lived resources (child processes, sockets)."""

    def __repr__(self):
        return f"<{type(self).__name__} name={self.name!r}>"
