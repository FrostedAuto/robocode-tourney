ROBOCODE TANK ROYALE - LAB PC KIT (for officers)
================================================

What it installs, for the logged-in Windows user only (NO admin rights needed):
  - Python 3.13.17 (python.org installer, per-user)          -> %LOCALAPPDATA%\Programs\Python\Python313
  - robocode-tank-royale 1.4.0 Python package (offline, from wheels\)
  - Java 21 runtime, Eclipse Temurin 21.0.13 (zip, no install) -> %USERPROFILE%\Robocode\jre
  - Robocode Tank Royale GUI 1.4.0                             -> %USERPROFILE%\Robocode
  - Python sample bots + starter bot MyBot                     -> %USERPROFILE%\Robocode\bots
  - "Start Robocode" launcher on the Desktop

Every file is checked against SHA256SUMS.txt before anything is installed.
All downloads came from the official sites (python.org, adoptium.net, github.com/robocode-dev).

HOW TO USE (about 3 minutes per PC)
  1. Copy this whole folder to the PC (USB stick or a network share). Don't run it from inside a zip.
  2. Double-click install.cmd. Wait for "Done".
  3. Double-click "Start Robocode" on the Desktop.
  4. In Robocode: Config > Bot Root Directories > Add > C:\Users\<you>\Robocode\bots > OK.
  5. Test: Battle > Start Battle > select MyBot, SpinBot, Walls > Boot > Start Battle.
     A battle with three tanks = the PC is ready.

Re-running install.cmd is safe: it skips what is already there and never overwrites the bots folder's MyBot.

IF SOMETHING FAILS
  - "Python did not install": run downloads\python-3.13.17-amd64.exe by hand, untick "Use admin
    privileges when installing py.exe", tick "Add python.exe to PATH", Install Now. Run install.cmd again.
  - Bots never appear in the battle window: start Robocode with "Start Robocode" (not by double-clicking
    the .jar), so it uses the kit's Python.
  - Windows firewall asks about Java: Cancel is fine (practice battles run on the PC itself).
  - Lab PCs that wipe profiles at logout lose the install: install again on the day.

SUBMITTING A BOT
  Open the upload page the officers announce (http://<address>:8080/submit) in a browser, enter the team
  key, choose the bot's .py and .json files (or a .zip of its folder), Upload. The page shows when the bot
  is accepted and connected.
