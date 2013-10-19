=================
LazyBlue
=================

A highly customizable utility to allow screen locking and unlocking via proximity of a Bluetooth device.

| Alex Roper
| aroper@umich.edu
| http://github.com/calmofthestorm

Usage
-------

- Pair the blue tooth device you wish to use with your computer (e.g, using bluetooth-wizard).
- Run lazy blue and verbose dry run mode to choose the signal strength at which you wish to lock and unlock::

      python lazyblue.py -m YOUR_DEVICE_MAC -n -v

- This will cause the program to output the current device strength as well as minimum and maximum strength observed and what actions would be taken. Experiment with the various distances of your Bluetooth device to determine at what distance you would like to lock and unlock your screen. Once you have decided, specify the lock strength with -S and unlock strength with -s. You can use these in dry mode to see when your screen would be locked and unlocked.

Use python lazyblue.py --help for complete options information. The basic setup is as follows:

Specify the lock command and unlock command you wish to use with -E and -e. Take a look at the help for other options such as running a command periodically to inhibit screensavers while nearby, run a second lock command if screen not unlocked in N seconds, various others.

If your lock program is one that runs in the foreground (such as xtrlock), specify the Option --foreground_lock and omit the unlock command. This will cause lazyblue to simply kill the screen lock instead of running an unlock command.

By default, if you unlock the screen by typing your password instead of via Bluetooth proximity, lazyblue will exit (this is to keep you from being locked out of your system should you lose the Bluetooth device, run out of battery, etc.) You may set --rearm_cooldown to a number of seconds to instead refused to real lock the screen for that many seconds.

If you wish to run as a daemon, specify -d or --daemon.

You may also specify your options in a configuration file, and then run with -c FILE instead of specifying them on the command line. Options given on the command line will override options set in the configuration file.

See the example_config directory for more examples of how you can use this program and configuration file syntax.

Security
----------

I have done my best to ensure this program works correctly, but writing security code is notoriously difficult. Please let me know if you find any bugs, particularly those that compromise security. Additionally, I strongly advise you to test the options you choose thoroughly to ensure that they make the program do exactly what you want.

See Also
----------

BlueProximity: https://www.google.com/search?q=blueproximity&oq=blueproximity&aqs=chrome..69i57j0l3.3348j0&sourceid=chrome&ie=UTF-8
