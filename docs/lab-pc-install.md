# Lab PC install guide (Windows, no admin rights)

For event staff. The lab PCs run Windows and need no admin rights: everything below installs
for the logged-in user only. Students practise on the lab PC and submit their bot through a web page.

## Fast way: the lab kit (about 3 minutes per PC)

`robocode-lab-kit.zip` (about 120 MB) has everything; every file in it is checked against official checksums.

1. Get the kit: open `http://<server>:8080/downloads` on the PC (the address is on the projector) and
   download **robocode-lab-kit.zip**, or copy it from the USB stick. Right-click → **Extract All** (Desktop is
   fine). Don't run it from inside the zip.
2. Double-click **`install.cmd`**, wait for **Done**.
3. Double-click **Start Robocode** on the Desktop.
4. Once per PC: **Config → Bot Root Directories → Add →** `C:\Users\<you>\Robocode\bots` → OK.
5. Test: **Battle → Start Battle**, select **MyBot**, **SpinBot**, **Walls** → **Boot** → **Start Battle**.
   Three tanks fighting = PC ready. Close the window.

> If the lab wipes profiles at logout, the install is gone next login. Install on the day, logged in as the
> account students will use.

## What the kit installs (and how to do it by hand if the kit fails)

| # | What | Version | Where from | No-admin notes |
|---|---|---|---|---|
| 1 | **Python** | 3.13.17 (64-bit) | python.org → Downloads → Windows → `python-3.13.17-amd64.exe` | Untick *Use admin privileges when installing py.exe*, tick **Add python.exe to PATH**, *Install Now* |
| 2 | **robocode-tank-royale** (Python package) | **1.4.0** exactly | `pip install robocode-tank-royale==1.4.0` (kit: offline from `wheels\`) | Per-user, no admin |
| 3 | **Java 21 runtime** | Eclipse Temurin 21.0.13 JRE | adoptium.net → Temurin 21 → Windows x64 **JRE .zip** | Use the **.zip**, not the .msi; unzip anywhere |
| 4 | **Robocode Tank Royale GUI** | **1.4.0** (must match the server) | github.com/robocode-dev/tank-royale → Releases → v1.4.0 → `robocode-tankroyale-gui-1.4.0.jar` | Just a file |
| 5 | **Python sample bots** | 1.4.0 | same release → `sample-bots-Python-1.4.0.zip` | Unzip into the bots folder |
| 6 | **Starter bot** `MyBot` | club version | kit `starter\MyBot` | Copy into the bots folder |
| 7 | Editor | IDLE (comes with Python) | — | Optional: VS Code *User Installer* (no admin) |
| 8 | Browser bookmark | — | the upload page `http://<vm-ip>:8080/submit` (address is on the projector and the board) | — |

By hand, start the GUI from a Command Prompt so it finds Python:
`set PATH=%LOCALAPPDATA%\Programs\Python\Python313;%PATH%` then
`"<jre folder>\bin\javaw.exe" -jar robocode-tankroyale-gui-1.4.0.jar`
(the GUI starts Python bots with the command `python`, so it must be the Python with the package).

## Troubleshooting on a PC

| Symptom | Fix |
|---|---|
| Bots never appear after **Boot** | Start Robocode with **Start Robocode** (not the .jar). Check `python -c "import robocode_tank_royale"` works in a Command Prompt |
| "Python did not install" | Run the Python installer by hand as in row 1, then `install.cmd` again |
| Windows Firewall asks about Java | **Cancel** is fine: practice battles stay on the PC |
| Bot shows up, then vanishes | It crashed: run it from IDLE (F5) to see the error |

## For students

- **Practise** on the lab PC: Battle → Start Battle → your bot + sample bots → Boot → Start.
- **Rename** your bot: class name, `.py` and `.json` must all be the same, e.g. `RedBaron` (letters, digits, `_`).
- **Submit** at the upload page with your team key: pick the `.py` + `.json` (or a `.zip` of the folder).
  The page says *accepted* and *connected ✔* when it's in. Upload again any time before uploads close; the
  newest one counts.
- The name in the arena is your **team name**.
