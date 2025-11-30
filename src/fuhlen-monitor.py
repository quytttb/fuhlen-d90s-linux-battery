#!/usr/bin/env python3
import usb.core
import usb.util
import time
import os
import json
import sys
import glob
import select

VID = 0x248a
PID = 0xfa02
OUTPUT_FILE = "/tmp/fuhlen_battery"
JSON_FILE = "/tmp/fuhlen_battery.json"

# --- CONFIGURATION ---
IDLE_THRESHOLD_LIGHT = 30   # Seconds to wait before reading (Light Sleep)
IDLE_THRESHOLD_DEEP = 150   # Seconds to stop reading (Deep Sleep)
FORCE_READ_INTERVAL = 900   # Seconds (15 mins) to force read if active continuously
MIN_READ_INTERVAL = 300     # Seconds (5 mins) minimum between reads

def find_mouse_event_device():
    """Find the /dev/input/eventX device corresponding to the mouse."""
    # Look for devices with matching VID/PID in sysfs
    # Pattern: /sys/class/input/event*/device/id/vendor
    for ev in glob.glob("/sys/class/input/event*"):
        try:
            with open(os.path.join(ev, "device/id/vendor"), "r") as f:
                vendor = int(f.read().strip(), 16)
            with open(os.path.join(ev, "device/id/product"), "r") as f:
                product = int(f.read().strip(), 16)
            
            if vendor == VID and product == PID:
                # Found it! Return /dev/input/eventX
                dev_name = os.path.basename(ev)
                return f"/dev/input/{dev_name}"
        except (IOError, ValueError):
            continue
    return None

def read_battery():
    dev = None
    needs_reattach = False
    try:
        # Reset device object each time to avoid stale handle
        dev = usb.core.find(idVendor=VID, idProduct=PID)
        if dev is None: return None

        # Detach kernel driver if active
        if dev.is_kernel_driver_active(0):
            try: 
                dev.detach_kernel_driver(0)
                needs_reattach = True
            except usb.core.USBError: pass
        else:
            # If not active, assume we might need to reattach it later anyway 
            # to ensure it's in a good state, or maybe it was already detached by a previous failed run.
            # But be careful not to attach if it wasn't supposed to be attached?
            # For a mouse, it SHOULD be attached.
            needs_reattach = True

        # Claim interface
        try:
            usb.util.claim_interface(dev, 0)
        except usb.core.USBError:
            # If claim fails, maybe device is busy or gone
            return None
        
        # Magic Command
        try:
            dev.write(0x05, b'\x05\x24\xfa\x48' + b'\x00'*28, timeout=1000)
        except usb.core.USBError:
            return None
        
        bat = None
        for _ in range(15):
            try:
                data = dev.read(0x84, 64, timeout=100)
                if data and data[0] == 0x05:
                    bat = int((data[4] - 50) / 2)
                    break
            except usb.core.USBError: pass
            time.sleep(0.05)
        
        return bat
    except Exception as e:
        return None
    finally:
        if dev:
            # Release the interface first
            try: usb.util.dispose_resources(dev)
            except: pass
            
            # Re-attach kernel driver if needed
            if needs_reattach:
                try: dev.attach_kernel_driver(0)
                except: pass

def update_output(bat, history, max_history=5):
    final_bat = None
    if bat is not None:
        history.append(bat)
        if len(history) > max_history:
            history.pop(0)
        if history:
            final_bat = int(round(sum(history) / len(history)))
    else:
        history.clear()
        final_bat = None
    
    status_text = f"{final_bat}%" if final_bat is not None else "N/A"
    try:
        with open(OUTPUT_FILE, "w") as f:
            f.write(status_text)
    except IOError: pass
        
    data = {"percentage": final_bat if final_bat is not None else 0, "is_present": final_bat is not None}
    try:
        with open(JSON_FILE, "w") as f:
            json.dump(data, f)
    except IOError: pass
    
    return history

def main():
    history = []
    last_read_time = 0
    last_activity_time = time.time()
    
    event_path = find_mouse_event_device()
    event_file = None
    
    print(f"Monitoring started. Mouse event device: {event_path}")

    while True:
        current_time = time.time()
        
        # 1. Check for mouse activity
        if event_path and os.path.exists(event_path):
            try:
                if event_file is None:
                    event_file = open(event_path, "rb")
                    # Set non-blocking
                    os.set_blocking(event_file.fileno(), False)
                
                # Read all available events to clear buffer and update timestamp
                has_activity = False
                while True:
                    # select is safer than direct read for non-blocking check
                    r, _, _ = select.select([event_file], [], [], 0)
                    if r:
                        # Read 24 bytes (struct input_event)
                        data = event_file.read(24) 
                        if data:
                            has_activity = True
                        else:
                            break
                    else:
                        break
                
                if has_activity:
                    last_activity_time = current_time
                    
            except Exception:
                # If file reading fails (e.g. device unplugged), reset
                if event_file: 
                    try: event_file.close()
                    except: pass
                event_file = None
                event_path = find_mouse_event_device() # Try to find again
        else:
            # Device not found, try to find it
            event_path = find_mouse_event_device()
            last_activity_time = current_time # Assume active to avoid immediate sleep logic issues

        # 2. Calculate Idle Time
        idle_time = current_time - last_activity_time
        time_since_last_read = current_time - last_read_time
        
        should_read = False
        
        # Logic:
        # A. Light Sleep (Idle > 30s) AND (Not read recently) -> READ (Best time!)
        if (idle_time > IDLE_THRESHOLD_LIGHT) and (idle_time < IDLE_THRESHOLD_DEEP):
            if time_since_last_read > MIN_READ_INTERVAL:
                should_read = True
                
        # B. Force Read (Active for too long) -> READ (Accept lag)
        elif (idle_time < 1.0): # Active
            if time_since_last_read > FORCE_READ_INTERVAL:
                should_read = True
                
        # C. Deep Sleep (Idle > 150s) -> DO NOTHING
        
        # 3. Execute Read if needed
        if should_read:
            bat = read_battery()
            history = update_output(bat, history)
            last_read_time = time.time()
            # Reset activity time slightly to avoid double-reading immediately
            # (though MIN_READ_INTERVAL handles this too)
        
        # 4. If device is gone (bat is None), update output to N/A periodically
        if event_path is None and time_since_last_read > 10:
             # Try reading to confirm it's really gone
             bat = read_battery()
             history = update_output(bat, history)
             last_read_time = time.time()

        time.sleep(1) # Check every second

if __name__ == "__main__":
    main()
