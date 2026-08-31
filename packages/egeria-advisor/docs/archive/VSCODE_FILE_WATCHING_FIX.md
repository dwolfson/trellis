# VSCode File Watching Fix

## Problem

VSCode shows "Unable to watch for file changes in this large workspace" error. This happens when the number of files exceeds the system's inotify watch limit.

## Current Status

Current limit: **65,536** (too low for large projects)  
Recommended limit: **524,288**

## Solution

### Option 1: Temporary Fix (Until Reboot)

Run this command to increase the limit temporarily:

```bash
sudo sysctl fs.inotify.max_user_watches=524288
```

### Option 2: Permanent Fix (Recommended)

1. **Edit the sysctl configuration:**

```bash
sudo nano /etc/sysctl.conf
```

2. **Add this line at the end of the file:**

```
fs.inotify.max_user_watches=524288
```

3. **Save and exit** (Ctrl+X, then Y, then Enter)

4. **Apply the changes:**

```bash
sudo sysctl -p
```

5. **Verify the new limit:**

```bash
cat /proc/sys/fs/inotify/max_user_watches
```

Should show: `524288`

6. **Reload VSCode window:**
   - Press `Ctrl+Shift+P`
   - Type "Reload Window"
   - Press Enter

## Alternative: Exclude Directories from Watching

If you don't want to increase system limits, you can exclude certain directories from VSCode's file watching.

### Add to VSCode settings.json:

```json
{
  "files.watcherExclude": {
    "**/.git/objects/**": true,
    "**/.git/subtree-cache/**": true,
    "**/node_modules/**": true,
    "**/.venv/**": true,
    "**/data/cache/**": true,
    "**/mlruns/**": true,
    "**/__pycache__/**": true,
    "**/*.pyc": true
  }
}
```

### To edit VSCode settings:

1. Press `Ctrl+Shift+P`
2. Type "Preferences: Open Settings (JSON)"
3. Add the `files.watcherExclude` section
4. Save the file

## Explanation

### What is inotify?

- Linux kernel subsystem for monitoring file system events
- VSCode uses it to detect file changes automatically
- Each watched file/directory consumes one "watch"

### Why increase the limit?

Large projects like egeria-advisor have many files:
- Source code files
- Virtual environment files (.venv)
- Cache files (data/cache)
- MLflow runs (mlruns)
- Git objects

Total files can easily exceed 65,536.

### Is 524,288 safe?

Yes! This is a commonly recommended value that:
- Works well for large projects
- Has minimal memory impact (~1-2 MB)
- Is used by many developers

## Troubleshooting

### Still seeing the error after increasing limit?

1. **Restart VSCode completely** (not just reload window)
2. **Check the limit was applied:**
   ```bash
   cat /proc/sys/fs/inotify/max_user_watches
   ```
3. **Check for other limits:**
   ```bash
   cat /proc/sys/fs/inotify/max_user_instances
   cat /proc/sys/fs/inotify/max_queued_events
   ```

### Want to increase other inotify limits?

Add these to `/etc/sysctl.conf`:

```
fs.inotify.max_user_watches=524288
fs.inotify.max_user_instances=512
fs.inotify.max_queued_events=32768
```

Then run: `sudo sysctl -p`

## Quick Commands Summary

```bash
# Check current limit
cat /proc/sys/fs/inotify/max_user_watches

# Temporary increase (until reboot)
sudo sysctl fs.inotify.max_user_watches=524288

# Permanent increase
echo "fs.inotify.max_user_watches=524288" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p

# Verify
cat /proc/sys/fs/inotify/max_user_watches
```

## References

- [VSCode File Watching Documentation](https://code.visualstudio.com/docs/setup/linux#_visual-studio-code-is-unable-to-watch-for-file-changes-in-this-large-workspace-error-enospc)
- [Linux inotify Documentation](https://man7.org/linux/man-pages/man7/inotify.7.html)

---

**Note**: You'll need sudo/root access to make these changes. If you don't have sudo access, use the VSCode settings exclusion method instead.