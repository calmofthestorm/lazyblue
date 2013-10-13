import bluetooth
import unittest
import mock
import time
import StringIO

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

class test_Monitor(unittest.TestCase):
  def setUp(self):
    lazyblue.config = Config(lazyblue.DEFAULT_OPTIONS)
    self.connection = mock.Mock(lazyblue.Connection, autospec=True)
    self.connection.get_signal_strength.return_value = -1
    self.monitor = lazyblue.Monitor(self.connection)

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

  @mock.patch("lazyblue.Monitor.lock_screen")
  @mock.patch("lazyblue.Monitor.unlock_screen")
  def test_transition_nop(self, unlock_screen, lock_screen):
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
    self.assertEqual(lock_screen.call_count, 0)
    self.assertEqual(unlock_screen.call_count, 0)

  @mock.patch("lazyblue.Monitor.lock_screen")
  @mock.patch("lazyblue.Monitor.unlock_screen")
  def test_transition_change(self, unlock_screen, lock_screen):
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
          lock_screen.reset_mock()
          unlock_screen.reset_mock()
          self.monitor.count = count - lazyblue.config.poll_interval
          self.monitor.state = starting_state
          self.monitor.last_locked = 0
          self.monitor.last_rearm = 0
          self.monitor.transition(opposite_state)

          if count >= transition_time:
            self.assertEqual(self.monitor.count, 0)
            self.assertEqual(self.monitor.state, other_state)
            if starting_state == lazyblue._LOCKED:
              self.assertEqual(lock_screen.call_count, 0)
              self.assertEqual(unlock_screen.call_count, 1)
            else:
              self.assertEqual(lock_screen.call_count, 1)
              self.assertEqual(unlock_screen.call_count, 0)
          else:
            self.assertEqual(self.monitor.count, count)
            self.assertEqual(self.monitor.state, starting_state)
            self.assertEqual(lock_screen.call_count, 0)
            self.assertEqual(unlock_screen.call_count, 0)

  @mock.patch("lazyblue.Monitor.lock_screen")
  @mock.patch("time.time")
  def test_transition_lock_cooldown(self, clock, lock_screen):
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
    self.assertEqual(lock_screen.call_count, 0)

    clock.return_value = self.monitor.last_locked + 15
    self.monitor.transition(lazyblue._GONE)
    self.assertEqual(lock_screen.call_count, 1)

    # rearm cooldown
    lock_screen.reset_mock()
    self.monitor.count = 10
    self.monitor.state = lazyblue._UNLOCKED
    self.monitor.last_locked = 10000
    self.monitor.last_rearm = 10000

    clock.return_value = self.monitor.last_rearm + 15
    self.monitor.transition(lazyblue._GONE)
    self.assertEqual(lock_screen.call_count, 0)

    clock.return_value = self.monitor.last_rearm + 25
    self.monitor.transition(lazyblue._GONE)
    self.assertEqual(lock_screen.call_count, 1)

  @mock.patch("time.time")
  @mock.patch("sys.exit")
  @mock.patch("os.system")
  def test_unlock_screen(self, system, mock_exit, clock):
    # simple case
    lazyblue.config.rearm_cooldown = 0
    system.return_value = lazyblue.signal.SIGKILL
    self.monitor.unlock_screen()
    self.assertEqual(mock_exit.call_count, 0)

    # manual no rearm
    system.return_value = 0
    self.monitor.unlock_screen()
    self.assertEqual(mock_exit.call_count, 1)

    # manual with rearm
    lazyblue.config.rearm_cooldown = 10
    system.return_value = 0
    clock.return_value = 824
    self.monitor.unlock_screen()
    self.assertEqual(mock_exit.call_count, 1)
    self.assertEqual(self.monitor.last_rearm, 824)

    # formatting
    self.monitor.lock_pid = 824
    lazyblue.config.unlock_command = "kill %(pid)s # kill %(pid)s"
    self.monitor.unlock_screen()
    system.assert_called_with("kill 824 # kill 824")

  @mock.patch("os.fork")
  @mock.patch("os._exit")
  @mock.patch("os.system")
  def test_lock_screen(self, system, mock_exit, fork):
    self.lock_pid = None

    # child calls and exits using low-level exit (to avoid doing wrong cleanup)
    fork.return_value = 0 
    self.monitor.lock_screen()
    self.assertEqual(mock_exit.call_count, 1)
    system.assert_called_with(lazyblue.config.lock_command)

    # parent does not block
    fork.return_value = 824
    self.monitor.lock_screen()
    self.assertEqual(mock_exit.call_count, 1)
    self.assertEqual(system.call_count, 1)

    self.assertEqual(self.monitor.lock_pid, 824)
