import argparse
import ConfigParser
import os
import time
import threading
import signal
import subprocess
import sys

import bluetooth
import bluetooth._bluetooth as bluez

DEFAULT_OPTIONS = {
    # lock the screen when signal strength is less than or equal to
    # LOCK_STRENGTH for config.lock_time seconds.
    "lock_strength": -2,
    "lock_time": 6,

    # unlock the screen when signal strength is equal to or greater than
    # or equal to UNLOCK_STRENGTH for config.unlock_time seconds.
    "unlock_strength": 0,
    "unlock_time": 1,

    # only lock the screen once per config.lock_cooldown seconds. this is a
    # failsafe to prevent you from being locked out of your computer due to
    # constant locking if there is a bug.
    "lock_cooldown": 15,

    # if nonzero, wait this many seconds to re-arm after a user unlocks the
    # screen manually raher than via Bluetooth. If 0, exit in such a situation.
    "rearm_cooldown": 0,

    # how often to poll the signal strength.
    "poll_interval": 1,

    # how often to attempt to connect to the device when it is connected.
    "connect_interval": 15,

    # screen locking command.
    "lock_command": "",

    # screen unlocking command
    "unlock_command": "",
  }

#######################################################################

# Screen states for state machine
_LOCKED = "locked"
_UNLOCKED = "unlocked"

# Device states for state machine
_HERE = "here"
_GONE = "gone"
_NEITHER = "neither"

def _strength_to_state(strength):
  """convert signal strength to appropriate state constant."""
  if strength < config.lock_strength:
    return _GONE
  elif strength >= config.unlock_strength:
    return _HERE
  else:
    return _NEITHER

class Connection(object):
  """responsible for establishing and maintaining a connection to the bluetooth
     device."""

  def __init__(self, mac, channel):
    self.mac = mac
    self.channel = channel
    self.sock = None
    self.last_connected = 0
    self._attempt_reconnect()

  def _attempt_reconnect(self):
    """attempt to reestablish the bluetooth connection, closing an
       existing connection if necessary and respecting CONNECT_INTERVAL by
       silently failing without trying if necessary."""
    try:
      if self.sock is not None:
        self.sock.close()
        self.sock = None
      if time.time() - self.last_connected < config.connect_interval:
        return
      self._connect()
    except bluetooth.btcommon.BluetoothError:
      pass

  def _connect(self):
    """connect to the bluetooth device."""
    self.last_connected = time.time()
    self.sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM, bluez.btsocket())
    self.sock.settimeout(0.01)
    time.sleep(0.1) # grrrr necessary to avoid "fd in bad state" errors
    self.sock.connect((self.mac, self.channel))

  def get_signal_strength(self):
    """get the device's current signal strength, reestablishing the connection
       if necessary"""
    reconnect = False
    if self.sock is None:
      reconnect = True
    else:
      try:
        self.sock.recv(1)
      except bluetooth.btcommon.BluetoothError, ex:
        if ex.message != "timed out":
          reconnect = True
    if reconnect:
      self._attempt_reconnect()
    devices = list(os.popen("hcitool rssi " + self.mac + " 2>/dev/null", "r"))
    if devices and ":" in devices[0]:
      return int(devices[0].split(":")[1].strip())
    else:
      return -255

class Monitor(object):
  """responsible for controlling screen locking and state transitions."""

  def __init__(self, connection):
    self.connection = connection
    self.last_poll = 0
    self.state = _UNLOCKED
    self.count = 0
    self.last_locked = 0
    self.last_rearm = 0
    self.lock_shell = None
    self.lock = threading.RLock()

  def poll(self):
    """poll the system once and execute any necessary actions, respecting
       config.poll_interval by sleeping until it is time for the next poll."""
    with self.lock:
      delta = time.time() - self.last_poll
      if delta < config.poll_interval:
        self.lock.release()
        time.sleep(config.poll_interval - delta)
        self.lock.acquire()
      self.last_poll = time.time()
      self.update(self.connection.get_signal_strength())

  def update(self, strength):
    """perform actions based on an observation of given strength."""
    with self.lock:
      self.transition(_strength_to_state(strength))
      print (("lock_state: %s\tbluetooth_state: %s\tchange_time: %.2f\t"
              "last_locked: %i\tsignal_strength: %i\tmax_strength: %i\t"
              "min_strength: %i\trearm_count: %i" %
              (self.state,
              _strength_to_state(strength),
              self.count,
              self.last_locked,
              strength, 0, 0,
              self.last_rearm)))

  def transition(self, signal_state):
    """performs state machine transition and necessary actions."""
    with self.lock:
      if signal_state is _NEITHER:
        # Signal not either way.
        self.count = 0
      elif ((self.state == _UNLOCKED and signal_state == _HERE) or
          (self.state == _LOCKED and signal_state == _GONE)):
        # Stay in same state.
        self.count = 0
      else:
        # Consider changing lock state.
        self.count += config.poll_interval

        if self.state == _LOCKED and self.count >= config.unlock_time:
          self.count = 0
          self.unlock_screen()
          self.state = _UNLOCKED
        elif (self.state == _UNLOCKED and self.count >= config.lock_time):
          if (self.last_locked + config.lock_cooldown <= time.time() and
              self.last_rearm + config.rearm_cooldown <= time.time()):
            self.state = _LOCKED
            self.lock_screen()
            self.count = 0
            self.last_locked = time.time()

  def poll_loop(self, count=None):
    """poll repeatedly the specified number of times, or forever if
       count=None."""
    while count is None or count > 0:
      self.poll()
      if count is not None:
        count -= 1

  def unlock_screen(self):
    """execute the screen unlock command"""
    if config.unlock_command:
      os.system(config.unlock_command)
    else:
      self.lock_shell.terminate()
      os.system("sudo killall vlock-main")
      self.state = _UNLOCKED

  def lock_screen(self):
    """execute the screen lock command"""
    threading.Thread(target=self.lock_main).start()

  def lock_main(self):
    if not config.lock_command:
      opts = {
          "env":{"USER":os.getlogin()},
        }
      executable = "sudo vlock -a -n"
    else:
      opts = {}
      executable = config.lock_command

    self.lock_shell = subprocess.Popen(
        executable,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=True,
        **opts
      )

    self.lock_shell.communicate("")
    with self.lock:
      if self.lock_shell.returncode not in (signal.SIGKILL, signal.SIGTERM):
        # Process died by manual user logout OR is non-blocking.
        if not config.unlock_command:
          # If no unlock_command, process should have been killed.
          # Need to rearm.
          if config.rearm_cooldown == 0:
            sys.exit()
          else:
            self.last_rearm = time.time()
            self.count = 0
            self.state = _UNLOCKED

class DryMonitor(Monitor):
  """monitor for dry runs that logs state information copiously."""
  def __init__(self, connection):
    self.max_strength = -255
    self.min_strength = 0
    Monitor.__init__(self, connection)

  def unlock_screen(self):
    print
    print "*" * 80
    print "unlock screen\n"

  def lock_screen(self):
    print
    print "*" * 80
    print "lock screen\n"

  def update(self, strength):
    Monitor.update(self, strength)

    self.max_strength = (strength if self.max_strength is None
                         else max(strength, self.max_strength))
    self.min_strength = (strength if self.min_strength is None
                         else min(strength, self.min_strength))

    print (("lock_state: %s\tbluetooth_state: %s\tchange_time: %.2f\t"
            "last_locked: %i\tsignal_strength: %i\tmax_strength: %i\t"
            "min_strength: %i\trearm_count: %i" %
            (self.state,
             _strength_to_state(strength),
             self.count,
             self.last_locked,
             strength,
             self.max_strength,
             self.min_strength,
             self.last_rearm)))

def parse_arguments():
  conf_parser = argparse.ArgumentParser(add_help=False)
  conf_parser.add_argument("-c", "--conf_file",
                           help="Specify config file", metavar="FILE")
  args, remaining_argv = conf_parser.parse_known_args()
  defaults = DEFAULT_OPTIONS.copy()

  if args.conf_file:
    config = ConfigParser.SafeConfigParser()
    config.read([args.conf_file])
    defaults.update(config.items("Defaults"))

  parser = argparse.ArgumentParser(
      parents=[conf_parser],
      description=__doc__,
      formatter_class=argparse.RawDescriptionHelpFormatter,
    )

  parser.set_defaults(**defaults)

  parser.add_argument("-m", "--device_mac", metavar="MAC",
      help=("mac address of your phone or other bluetooth device "
            "that you wish to use for locking. Must already be paired.")
    )

  parser.add_argument("-S", "--lock_strength", metavar="STRENGTH", type=int,
      help="consider device gone when signal strength < STRENGTH."
    )

  parser.add_argument("-s", "--unlock_strength", metavar="STRENGTH", type=int,
      help="consider device here when signal strength >= STRENGTH."
    )

  parser.add_argument("-T", "--lock_time", metavar="SECONDS", type=int,
      help="lock screen when device gone for SECONDS."
    )

  parser.add_argument("-t", "--unlock_time", metavar="SECONDS", type=int,
      help="unlock screen when device here for SECONDS."
    )

  parser.add_argument("-C", "--lock_cooldown", metavar="SECONDS", type=int,
      help="lock screen at most once per SECONDS."
    )

  parser.add_argument("-r", "--rearm_cooldown", metavar="SECONDS", type=int,
      help=("wait SECONDS to relax screen if user unlocks it manually. "
            "set to zero to exit whenever user unlock screen manually "
            "(default). This is probably only useful if you are using "
            "kill as the unlock command. (eg, with vlock)")
    )

  parser.add_argument("-i", "--poll_interval", metavar="SECONDS", type=float,
      help="poll signal strength once per SECONDS."
    )

  parser.add_argument("-I", "--connect_interval", metavar="SECONDS", type=int,
      help=("if device is not connected, attempt to connect "
            "at most once per SECONDS.")
    )

  parser.add_argument("-E", "--lock_command", metavar="CMD",
      help="command to run to lock the screen"
    )

  parser.add_argument("-e", "--unlock_command", metavar="CMD",
      help="command to run to unlock the screen"
    )

  parser.add_argument("-n", "--dry_run", action="store_true",
      help=("display to console signal strength and what will be "
            "done rather than actually locking screen. useful for figuring "
            "out appropriate signal strengths.")
    )

  config = parser.parse_args(remaining_argv)

  # Validate arguments
  valid = True
  if config.device_mac is None:
    sys.stderr.write("You must specify the MAC address of your device.\n")
    valid = False

  for arg in ("lock_time", "unlock_time", "lock_cooldown",
              "rearm_cooldown", "connect_interval"):
    value = getattr(config, arg)
    try:
      setattr(config, arg, int(value))
      if value < 0:
        raise ValueError()
    except ValueError:
      sys.stderr.write("%s must be a positive integer, not %s.\n" %
                       (arg, value))
      valid = False

  try:
    config.poll_interval = float(config.poll_interval)
  except ValueError:
    sys.stderr.write("poll_interval must be a number, not %s.\n" %
                     config.poll_interval)
    valid = False

  for arg in ("lock_strength", "unlock_strength"):
    value = getattr(config, arg)
    try:
      setattr(config, arg, int(value))
    except ValueError:
      sys.stderr.write("%s must be an integer, not %s.\n" % (arg, value))
      valid = False

  if config.lock_strength >= config.unlock_strength:
    sys.stderr.write("Lock strength must be < unlock strength.\n")
    valid = False

  if not valid:
    sys.exit()

  return config

if __name__ == "__main__":
  config = parse_arguments()
  monitor = (DryMonitor if config.dry_run else Monitor)
  monitor(Connection(config.device_mac, 1)).poll_loop()
