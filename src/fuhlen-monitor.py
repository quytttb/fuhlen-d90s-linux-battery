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
NA_DEBOUNCE_COUNT = 3       # Number of consecutive failures before showing N/A

# Global cache for device path + signature
_cached_event_info = (None, None)

def _build_device_signature(ev_path):
    """Create a signature that changes across unplug/replug events."""
    try:
        real_dev_path = os.path.realpath(os.path.join(ev_path, "device"))
        return real_dev_path
    except Exception:
        return None

def find_mouse_event_device():
    """Find the /dev/input/eventX device corresponding to the mouse."""
    global _cached_event_info
    cached_path, cached_sig = _cached_event_info
    
    # Check if cached path is still valid
    if cached_path and os.path.exists(cached_path):
        return _cached_event_info
        
    # Look for devices with matching VID/PID in sysfs
    # Pattern: /sys/class/input/event*/device/id/vendor
    for ev in glob.glob("/sys/class/input/event*"):
        try:
            # Check if path exists before opening to avoid race condition
            vendor_path = os.path.join(ev, "device/id/vendor")
            product_path = os.path.join(ev, "device/id/product")
            
            if not (os.path.exists(vendor_path) and os.path.exists(product_path)):
                continue
                
            with open(vendor_path, "r") as f:
                vendor = int(f.read().strip(), 16)
            with open(product_path, "r") as f:
                product = int(f.read().strip(), 16)
            
            if vendor == VID and product == PID:
                # Found it! Return /dev/input/eventX along with a unique signature
                dev_name = os.path.basename(ev)
                device_signature = _build_device_signature(ev)
                event_path = f"/dev/input/{dev_name}"
                _cached_event_info = (event_path, device_signature)
                print(f"Device found at: {event_path} (signature={device_signature})")
                return _cached_event_info
        except (IOError, ValueError):
            continue
            
    _cached_event_info = (None, None)
    return _cached_event_info

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

def update_output(bat, history, max_history=5, na_counter=0):
    final_bat = None
    
    # Logic to handle N/A debounce
    if bat is not None:
        # Reset NA counter externally if needed, but here we just process valid data
        history.append(bat)
        if len(history) > max_history:
            history.pop(0)
        if history:
            final_bat = int(round(sum(history) / len(history)))
    else:
        # If bat is None (read failed), we don't clear history immediately
        # We only return None for final_bat if we really want to show N/A
        # But the caller handles the debounce logic.
        # Here we just return the last known good value if history exists
        if history:
             final_bat = int(round(sum(history) / len(history)))
        else:
             final_bat = None

    # Only write if value changed or file doesn't exist
    current_text = f"{final_bat}%" if final_bat is not None else "N/A"
    
    should_write = True
    if os.path.exists(OUTPUT_FILE):
        try:
            with open(OUTPUT_FILE, "r") as f:
                if f.read().strip() == current_text:
                    should_write = False
        except: pass
    
    if should_write:
        try:
            with open(OUTPUT_FILE, "w") as f:
                f.write(current_text)
        except IOError: pass
        
    # JSON update (always update timestamp or similar if we had one, but here just value)
    # To save IO, we can also skip JSON write if value same
    # But for simplicity let's keep JSON sync with text
    if should_write:
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
    na_failure_count = 0 # Counter for consecutive failures
    
    # Try to load last known value to show something immediately
    try:
        if os.path.exists(JSON_FILE):
            with open(JSON_FILE, 'r') as f:
                d = json.load(f)
                if d.get('percentage') and d.get('is_present'):
                    start_bat = int(d['percentage'])
                    history.append(start_bat)
                    # Also write to text file to ensure executor sees it if it restarted
                    with open(OUTPUT_FILE, 'w') as f_out:
                        f_out.write(f"{start_bat}%")
    except: pass
    
    event_path, event_signature = find_mouse_event_device()
    last_known_signature = None # Track to detect reconnection
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
                event_path, event_signature = find_mouse_event_device() # Try to find again
                if event_path is None:
                    last_known_signature = None
        else:
            # Device not found, try to find it
            if event_file:
                try: event_file.close()
                except: pass
                event_file = None
            event_path, event_signature = find_mouse_event_device()
            if event_path is None:
                last_known_signature = None
            last_activity_time = current_time # Assume active to avoid immediate sleep logic issues

        # 2. Calculate Idle Time
        idle_time = current_time - last_activity_time
        time_since_last_read = current_time - last_read_time
        
        should_read = False
        
        # Logic:
        # A. Startup or New Connection -> Force Read Immediately
        if (last_read_time == 0) or (event_path and event_signature and (event_signature != last_known_signature)):
            print(f"New connection detected or startup. Event path: {event_path} (signature={event_signature})")
            should_read = True
            if event_signature:
                last_known_signature = event_signature
            
        # B. Light Sleep (Idle > 30s) AND (Not read recently) -> READ (Best time!)
        elif (idle_time > IDLE_THRESHOLD_LIGHT) and (idle_time < IDLE_THRESHOLD_DEEP):
            if time_since_last_read > MIN_READ_INTERVAL:
                should_read = True
                
        # C. Force Read (Active for too long) -> READ (Accept lag)
        elif (idle_time < 1.0): # Active
            if time_since_last_read > FORCE_READ_INTERVAL:
                should_read = True
                
        # D. Deep Sleep (Idle > 150s) -> DO NOTHING
        
        # 3. Execute Read if needed
        if should_read:
            bat = read_battery()
            
            if bat is None:
                na_failure_count += 1
            else:
                na_failure_count = 0 # Reset on success
            
            # Only clear history (show N/A) if failed multiple times
            if bat is None and na_failure_count < NA_DEBOUNCE_COUNT:
                # Keep old history, don't update output yet (or update with old value)
                # We just skip update_output to keep file as is
                pass 
            elif bat is None and na_failure_count >= NA_DEBOUNCE_COUNT:
                # Real failure, clear history
                history.clear()
                update_output(None, history)
            else:
                # Success
                history = update_output(bat, history)
                
            last_read_time = time.time()
        
        # 4. If device is gone (bat is None), update output to N/A periodically
        if event_path is None and time_since_last_read > 10:
             # Try reading to confirm it's really gone
             bat = read_battery()
             if bat is None:
                 na_failure_count += 1
                 if na_failure_count >= NA_DEBOUNCE_COUNT:
                     history.clear()
                     update_output(None, history)
             else:
                 na_failure_count = 0
                 history = update_output(bat, history)
                 
             last_read_time = time.time()

        time.sleep(1) # Check every second

if __name__ == "__main__":
    main()
