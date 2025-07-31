#!/bin/bash
# Block notify script for Salvium node
# /home/salvium/scripts/block_notify.sh

# Log the block notification
echo "$(date): New block notification: $1" >> /home/salvium/logs/block_notify.log

# Signal the pool process to refresh block template
pkill -USR1 -f "salvium-pool"

exit 0

