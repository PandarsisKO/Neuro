#!/bin/bash
# Keeps this Mac from sleeping (display, system, disk) for as long as this window stays open — nothing in
# System Settings changes, and normal sleep resumes the moment you close this window or Ctrl+C it.
#
# Needed overnight so Claude can keep reaching this Mac: the device bridge, the browser tools, and Finder/
# Terminal control all stop working the instant the machine sleeps or loses its network connection.
#
# Double-click this file. Leave the window open all night. Close it in the morning (or just let the Mac sleep
# normally again whenever you're done).
set -e
echo "Keeping this Mac awake (display + system + disk). Close this window to let it sleep normally again."
echo
exec caffeinate -disu
