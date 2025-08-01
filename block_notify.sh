#!/bin/bash
# Block notify script for Salvium node
# /home/salvium/scripts/block_notify.sh

# Log the block notification
echo "$(date): New block notification: $1" >> /home/salvium/logs/block_notify.log

# Get the main pid
MAIN_PID=$(systemctl show --property MainPID --value salvium-pool-leaf)

# Signal the pool process to refresh block template
if [ -n "$MAIN_PID" ] && [ "$MAIN_PID" != "0" ]; then
    kill -USR1 $MAIN_PID
    echo "$(date): Sent USR1 signal to PID $MAIN_PID" >> /home/salvium/logs/block_notify.log
else
    echo "$(date): ERROR - Could not get valid PID from systemd" >> /home/salvium/logs/block_notify.log
fi

exit 0

