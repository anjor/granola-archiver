#!/bin/bash
# Setup macOS launchd job for automatic archiving

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_FILE="$HOME/Library/LaunchAgents/com.granola.archiver.plist"

echo "Setting up Granola archiver launchd job..."
echo "Project directory: $PROJECT_DIR"

# Detect uv path
UV_PATH=$(which uv)
if [ -z "$UV_PATH" ]; then
    echo "Error: uv not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi
echo "uv path: $UV_PATH"

# Create plist file
cat > "$PLIST_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.granola.archiver</string>
    <key>ProgramArguments</key>
    <array>
        <string>$UV_PATH</string>
        <string>run</string>
        <string>archiver</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>StartInterval</key>
    <integer>1800</integer>
    <key>StandardOutPath</key>
    <string>/tmp/granola-archiver.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/granola-archiver.error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
EOF

echo "Created plist file: $PLIST_FILE"

# Unload existing job if present
if launchctl list | grep -q com.granola.archiver; then
    echo "Unloading existing job..."
    launchctl unload "$PLIST_FILE" 2>/dev/null || true
fi

# Load the job
echo "Loading launchd job..."
launchctl load "$PLIST_FILE"

# Check status
if launchctl list | grep -q com.granola.archiver; then
    echo "✓ Granola archiver launchd job installed successfully!"
    echo ""
    echo "The archiver will run every 30 minutes."
    echo ""
    echo "Useful commands:"
    echo "  View status:    launchctl list | grep granola"
    echo "  View logs:      tail -f /tmp/granola-archiver.log"
    echo "  View errors:    tail -f /tmp/granola-archiver.error.log"
    echo "  Unload job:     launchctl unload $PLIST_FILE"
    echo "  Reload job:     launchctl unload $PLIST_FILE && launchctl load $PLIST_FILE"
else
    echo "✗ Failed to install launchd job"
    exit 1
fi
