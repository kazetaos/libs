#!/bin/bash

# This script fixes audio in games that do not respect the system default audio device

TARGET_APP="$1"
shift
GAME_COMMAND=("$@")

if [ -z "$TARGET_APP" ] || [ ${#GAME_COMMAND[@]} -eq 0 ]; then
    echo "Usage: $0 \"Application Audio Name\" ./executable [arguments]"
    echo "Example: $0 \"FMOD Ex App\" ./'Gang Beasts.x86_64'"
    exit 1
fi

echo "Starting game: ${GAME_COMMAND[*]}"
"${GAME_COMMAND[@]}" &
GAME_PID=$!

# Background loop to catch the audio stream as soon as it initializes
(
    for i in {1..50}; do
        # Search the Pulse Audio layer for the custom application name string
        STREAM_ID=$(pactl list sink-inputs | grep -B 20 -i "application.name = \"$TARGET_APP\"" | grep "Sink Input #" | awk '{print $3}' | tr -d '#')
        SINK_NAME=$(pactl info | grep "Default Sink:" | awk '{print $3}')

        if [ ! -z "$STREAM_ID" ] && [ ! -z "$SINK_NAME" ]; then
            echo "Found stream ($STREAM_ID). Moving to default output ($SINK_NAME)..."
            pactl move-sink-input "$STREAM_ID" "$SINK_NAME"
            break
        fi
        sleep 0.1
    done
) &

# Ensure the terminal remains locked to the game process until it closes
wait $GAME_PID
