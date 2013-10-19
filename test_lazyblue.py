import bluetooth
import mock
import StringIO
import time
import unittest

import lazyblue

class Config(dict):
  def __getattr__(self, key):
    return self[key]

class test_helpers(unittest.TestCase):
  def setUp(self):
    lazyblue.config = Config(lazyblue.DEFAULT_OPTIONS)

  def test_strength_to_state(self):
    lazyblue.config.lock_strength = -10
    lazyblue.config.unlock_strength = -3
    self.assertEqual(lazyblue._HERE, lazyblue._strength_to_state(-1))
    self.assertEqual(lazyblue._HERE, lazyblue._strength_to_state(-3))
    self.assertEqual(lazyblue._NEITHER, lazyblue._strength_to_state(-9))
    self.assertEqual(lazyblue._NEITHER, lazyblue._strength_to_state(-10))
    self.assertEqual(lazyblue._GONE, lazyblue._strength_to_state(-11))
    self.assertEqual(lazyblue._GONE, lazyblue._strength_to_state(-255))

class test_Connection(unittest.TestCase):
  def setUp(self):
    lazyblue.config = Config(lazyblue.DEFAULT_OPTIONS)

  @mock.patch("lazyblue.Connection._connect")
  def test_attempt_reconnect(self, method):
    # creating an object should call connect
    connection = lazyblue.Connection("mac", 1)
    self.assertEqual(method.call_count, 1)

    # reconnect should close old socket
    sock = connection.sock = mock.Mock(bluetooth.BluetoothSocket, autospec=True)
    connection._attempt_reconnect()
    self.assertEqual(sock.close.call_count, 1)
    self.assertEqual(method.call_count, 2)

    # do not attempt to reconnect if cooldown has not expired
    connection.last_connected = time.time()
    connection._attempt_reconnect()
    self.assertEqual(method.call_count, 2)

    # should ignore bluetooth errors
    connection.last_connected = 0
    method.side_effect = bluetooth.btcommon.BluetoothError()
    connection._attempt_reconnect()

  @mock.patch("os.popen")
  @mock.patch("lazyblue.Connection._connect")
  def test_get_signal_strength_reconnect(self, connect_method, popen):
    connection = lazyblue.Connection("mac", 1)
    sock = connection.sock = mock.Mock(bluetooth.BluetoothSocket, autospec=True)
    popen.side_effect = lambda command, mode: StringIO.StringIO("RSSI return value: -17")

    # if recv returns don't reconnect.
    sock.recv.return_value = "1"
    self.assertEqual(connection.get_signal_strength(), -17)
    self.assertEqual(connect_method.call_count, 1)

    # if recv returns timeout don't reconnect
    sock.recv.side_effect = bluetooth.btcommon.BluetoothError("timed out")
    self.assertEqual(connection.get_signal_strength(), -17)
    self.assertEqual(connect_method.call_count, 1)

    # if recv receives a different error reconnect
    sock.recv.side_effect = bluetooth.btcommon.BluetoothError()
    self.assertEqual(connection.get_signal_strength(), -17)
    self.assertEqual(connect_method.call_count, 2)

    self.assertEqual(popen.call_count, 3)

  @mock.patch("os.popen")
  @mock.patch("lazyblue.Connection._connect")
  def test_get_signal_strength(self, connect_method, popen):
    connection = lazyblue.Connection("mac", 1)
    connection.sock = mock.Mock(bluetooth.BluetoothSocket, autospec=True)
    connection.sock.recv.side_effect = bluetooth.btcommon.BluetoothError("timed out")

    popen.side_effect = lambda command, mode: StringIO.StringIO("RSSI return value: -15")
    self.assertEqual(connection.get_signal_strength(), -15)

    popen.side_effect = lambda command, mode: StringIO.StringIO("Not connected.")
    self.assertEqual(connection.get_signal_strength(), -255)
    self.assertEqual(connect_method.call_count, 1)

class test_ScreenLocker(unittest.TestCase):
  def setUp(self):
    lazyblue.config = Config(lazyblue.DEFAULT_OPTIONS)
    self.screenlocker = lazyblue.ScreenLocker()

  @mock.patch("os.system")
  def test_unlock_screen(self, system):
    lazyblue.config.lock_command = "xscreensaver-command -l"
    self.screenlocker.lock_screen()
    system.assert_called_with(lazyblue.config.lock_command)

  @mock.patch("os.system")
  def test_lock_screen(self, system):
    lazyblue.config.unlock_command = "xscreensaver-command -d"
    self.screenlocker.unlock_screen()
    system.assert_called_with(lazyblue.config.unlock_command)

  @mock.patch("os.system")
  def test_simulate_activity(self, system):
    lazyblue.config.activity_command = "xscreensaver-command -p"
    self.screenlocker.simulate_activity()
    system.assert_called_with(lazyblue.config.activity_command)

  @mock.patch("os.system")
  def test_is_locked(self, system):
    lazyblue.config.status_command = "xscreensaver-command -time"
    system.return_value = True
    result = self.screenlocker.is_locked()
    system.assert_called_with(lazyblue.config.status_command)
    self.assertEqual(result, True)

    system.reset_mock()
    lazyblue.config.status_command = ""
    result = self.screenlocker.is_locked()
    system.assert_not_called()
    self.assertEqual(result, True)

class test_ForgroundScreenLocker(unittest.TestCase):
  def setUp(self):
    lazyblue.config = Config(lazyblue.DEFAULT_OPTIONS)
    self.screenlocker = lazyblue.ForegroundScreenLocker()
    self.screenlocker.lock_shell = mock.Mock(lazyblue.subprocess.Popen, autospec=True)

  @mock.patch("os.system")
  def test_unlock_screen(self, system):
    terminate = self.screenlocker.lock_shell.terminate
    self.screenlocker.unlock_screen()
    self.assertIsNone(self.screenlocker.lock_shell)
    terminate.assert_called()

  @mock.patch("os.system")
  def test_lock_screen(self, system):
    terminate = self.screenlocker.lock_shell.terminate
    self.screenlocker.unlock_screen()
    self.assertIsNone(self.screenlocker.lock_shell)
    terminate.assert_called()

  def test_is_locked(self):
    self.screenlocker.lock_shell.returncode = None
    self.assertEqual(self.screenlocker.is_locked(), True)
    self.screenlocker.lock_shell.poll.assert_called()

    self.screenlocker.lock_shell.returncode = 0
    poll = self.screenlocker.lock_shell.poll
    self.assertEqual(self.screenlocker.is_locked(), False)
    poll.assert_called()
    self.assertEqual(self.screenlocker.lock_shell, None)

    self.screenlocker.lock_shell = None
    self.assertEqual(self.screenlocker.is_locked(), False)

class test_Monitor(unittest.TestCase):
  def setUp(self):
    lazyblue.config = Config(lazyblue.DEFAULT_OPTIONS)
    self.connection = mock.Mock(lazyblue.Connection, autospec=True)
    self.screenlocker = mock.Mock(lazyblue.ScreenLocker, autospec=True)
    self.connection.get_signal_strength.return_value = -1
    self.monitor = lazyblue.Monitor(self.connection, self.screenlocker)

  @mock.patch("lazyblue.Monitor.update")
  @mock.patch("time.sleep")
  @mock.patch("time.time")
  def test_poll(self, clock, sleep, update):
    # if it's time to call again it should.
    last_poll = self.monitor.last_poll = 500
    clock.return_value = 505
    self.monitor.poll()
    self.assertEqual(sleep.call_count, 0)
    self.assertGreaterEqual(self.monitor.last_poll, last_poll + 5)
    update.assertCalledWith(-1)

    # verify we block where necessary
    last_poll = self.monitor.last_poll = 515.5
    clock.return_value = 514.75
    self.monitor.poll()
    sleep.assert_called_with(1.75)

   # rearm quit now
    self.monitor.state = lazyblue._LOCKED
    self.monitor.last_rearm = 519
    self.monitor.count = 20
    self.screenlocker.is_locked.return_value = False 
    lazyblue.config.rearm_cooldown = 0
    clock.return_value = 520
    self.assertRaises(SystemExit, self.monitor.poll)

   # rearm cooldown
    self.monitor.state = lazyblue._LOCKED
    self.monitor.last_rearm = 529
    self.monitor.count = 20
    self.screenlocker.is_locked.return_value = False 
    lazyblue.config.rearm_cooldown = 10
    clock.return_value = 535
    self.monitor.poll()
    self.assertEqual(self.monitor.last_rearm, 535)

  @mock.patch("lazyblue.Monitor.transition")
  def test_update(self, transition):
    lazyblue.config.lock_strength = -10
    lazyblue.config.unlock_strength = -3
    self.monitor.update(-8)
    transition.assert_called_with(lazyblue._NEITHER)

  @mock.patch("lazyblue.Monitor.poll")
  def test_poll_loop(self, poll):
    self.monitor.poll_loop(10)
    self.assertEqual(10, poll.call_count)

  def test_transition_nop(self):
    lazyblue.config.lock_time = 6
    lazyblue.config.unlock_time = 1
    times = range(8)
    for lazyblue.config.poll_interval in xrange(1, 3):
      # neither or matching means stay same and reset count.
      for lock_state in (lazyblue._LOCKED, lazyblue._UNLOCKED):
        match_state = (lazyblue._GONE if lock_state == lazyblue._LOCKED
                      else lazyblue._HERE)
        for device_state in (lazyblue._NEITHER, match_state):
          for count in times:
            self.monitor.count = count
            self.monitor.state = lock_state
            self.monitor.transition(device_state)
            self.assertEqual(self.monitor.count, 0)
            self.assertEqual(self.monitor.state, lock_state)
    self.assertEqual(self.screenlocker.lock_screen.call_count, 0)
    self.assertEqual(self.screenlocker.unlock_screen.call_count, 0)

  def test_transition_change(self):
    lazyblue.config.lock_time = 6
    lazyblue.config.unlock_time = 1
    times = range(8)
    for lazyblue.config.poll_interval in xrange(1, 3):
      # maybe change state depending on count.
      for starting_state in (lazyblue._UNLOCKED, lazyblue._LOCKED):
        other_state = (lazyblue._UNLOCKED if starting_state == lazyblue._LOCKED
                       else lazyblue._LOCKED)
        transition_time = (lazyblue.config.unlock_time if starting_state == lazyblue._LOCKED
                           else lazyblue.config.lock_time)
        opposite_state = (lazyblue._HERE if starting_state == lazyblue._LOCKED
                          else lazyblue._GONE)
        for count in times:
          self.screenlocker.lock_screen.reset_mock()
          self.screenlocker.unlock_screen.reset_mock()
          self.monitor.count = count - lazyblue.config.poll_interval
          self.monitor.state = starting_state
          self.monitor.last_locked = 0
          self.monitor.last_rearm = 0
          self.monitor.transition(opposite_state)

          if count >= transition_time:
            self.assertEqual(self.monitor.count, 0)
            self.assertEqual(self.monitor.state, other_state)
            if starting_state == lazyblue._LOCKED:
              self.assertEqual(self.screenlocker.lock_screen.call_count, 0)
              self.assertEqual(self.screenlocker.unlock_screen.call_count, 1)
            else:
              self.assertEqual(self.screenlocker.lock_screen.call_count, 1)
              self.assertEqual(self.screenlocker.unlock_screen.call_count, 0)
          else:
            self.assertEqual(self.monitor.count, count)
            self.assertEqual(self.monitor.state, starting_state)
            self.assertEqual(self.screenlocker.lock_screen.call_count, 0)
            self.assertEqual(self.screenlocker.unlock_screen.call_count, 0)

  @mock.patch("time.time")
  @mock.patch("sys.exit")
  def test_transition_lock_cooldown(self, sys_exit, clock):
    lazyblue.config.lock_time = 6
    lazyblue.config.unlock_time = 1
    lazyblue.config.lock_cooldown = 10
    lazyblue.config.rearm_cooldown = 20

    # lock cooldown
    self.monitor.count = 10
    self.monitor.state = lazyblue._UNLOCKED
    self.monitor.last_locked = 10000
    self.monitor.last_rearm = 0

    clock.return_value = self.monitor.last_locked + 5
    self.monitor.transition(lazyblue._GONE)
    self.assertEqual(self.screenlocker.lock_screen.call_count, 0)

    clock.return_value = self.monitor.last_locked + 15
    self.monitor.transition(lazyblue._GONE)
    self.assertEqual(self.screenlocker.lock_screen.call_count, 1)

    # rearm cooldown
    self.screenlocker.lock_screen.reset_mock()
    self.monitor.count = 10
    self.monitor.state = lazyblue._UNLOCKED
    self.monitor.last_locked = 10000
    self.monitor.last_rearm = 10000

    clock.return_value = self.monitor.last_rearm + 15
    self.monitor.transition(lazyblue._GONE)
    self.assertEqual(self.screenlocker.lock_screen.call_count, 0)

    clock.return_value = self.monitor.last_rearm + 25
    self.monitor.transition(lazyblue._GONE)
    self.assertEqual(self.screenlocker.lock_screen.call_count, 1)
    self.assertEqual(sys_exit.call_count, 0)

  @mock.patch("lazyblue.Monitor.transition")
  @mock.patch("time.time")
  def test_harden_lock(self, clock, transition):
    lazyblue.config.harden_time = 5
    self.monitor.count = 0
    self.monitor.last_locked = 1024
    self.monitor.state = lazyblue._LOCKED
    self.monitor.vlock = mock.Mock(lazyblue.VlockScreenLocker, autospec=True)

    clock.return_value = 1027
    self.monitor.update(-255)
    self.monitor.vlock.lock_screen.assert_not_called()
    transition.assert_called_with(lazyblue._GONE)

    clock.return_value = 1050
    self.monitor.update(-255)
    self.monitor.vlock.lock_screen.assert_called()
    transition.assert_called_with(lazyblue._GONE)

  @mock.patch("time.time")
  def test_harden_unlock(self, clock):
    lazyblue.config.harden_time = 5
    self.monitor.last_rearm = 0
    self.monitor.count = 1
    self.monitor.state = lazyblue._HARDENED
    clock.return_value = 1024

    self.monitor.vlock = mock.Mock(lazyblue.VlockScreenLocker, autospec=True)
    self.monitor.vlock.is_locked.return_value = True
    self.monitor.update(-255)
    self.assertEqual(self.monitor.last_rearm, 0)
    self.assertEqual(self.monitor.count, 1)
    self.assertEqual(self.monitor.state, lazyblue._HARDENED)
    self.monitor.vlock.unlock_screen.assert_not_called()

    self.monitor.vlock = mock.Mock(lazyblue.VlockScreenLocker, autospec=True)
    self.monitor.vlock.is_locked.return_value = False
    self.monitor.update(-255)
    self.assertEqual(self.monitor.last_rearm, 1024)
    self.assertEqual(self.monitor.count, 0)
    self.assertEqual(self.monitor.state, lazyblue._UNLOCKED)
    self.monitor.vlock.unlock_screen.assert_called()
