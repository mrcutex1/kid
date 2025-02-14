#!/bin/bash

# Start the watchdog in the background
python3 watchdog.py &
WATCHDOG_PID=$!

# Function to cleanup processes on exit
cleanup() {
    echo "Stopping processes..."
    kill $WATCHDOG_PID
    exit 0
}

# Register the cleanup function for SIGINT and SIGTERM
trap cleanup SIGINT SIGTERM

# Wait for the watchdog
wait $WATCHDOG_PID
