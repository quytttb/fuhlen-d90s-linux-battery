#!/usr/bin/env python3
import usb.core
import usb.util
import time
import os
import json
import sys

VID = 0x248a
PID = 0xfa02
OUTPUT_FILE = "/tmp/fuhlen_battery"
JSON_FILE = "/tmp/fuhlen_battery.json"

def read_battery():
    dev = None
    try:
        # Reset device object each time to avoid stale handle
        dev = usb.core.find(idVendor=VID, idProduct=PID)
        if dev is None: return None

        # Detach kernel driver if active
        if dev.is_kernel_driver_active(0):
            try: dev.detach_kernel_driver(0)
            except usb.core.USBError: pass

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

        # Clean up
        try:
            usb.util.dispose_resources(dev)
        except: pass
        
        try: 
            if dev: dev.attach_kernel_driver(0)
        except: pass
        
        return bat
    except Exception as e:
        # Log error to stderr if needed, but keep running
        return None
    finally:
        # Ensure resources are released if dev exists
        if dev:
            try: usb.util.dispose_resources(dev)
            except: pass

def main():
    history = []
    MAX_HISTORY = 5

    while True:
        try:
            bat = read_battery()
            
            final_bat = None

            if bat is not None:
                history.append(bat)
                if len(history) > MAX_HISTORY:
                    history.pop(0)
                
                # Calculate average to smooth out fluctuations
                if history:
                    final_bat = int(round(sum(history) / len(history)))
            else:
                # Device disconnected, clear history
                history = []
                final_bat = None
            
            # 1. Ghi file text đơn giản (cho Executor)
            status_text = f"{final_bat}%" if final_bat is not None else "N/A"
            try:
                with open(OUTPUT_FILE, "w") as f:
                    f.write(status_text)
            except IOError: pass
                
            # 2. Ghi file JSON (cho script nâng cao)
            data = {"percentage": final_bat if final_bat is not None else 0, "is_present": final_bat is not None}
            try:
                with open(JSON_FILE, "w") as f:
                    json.dump(data, f)
            except IOError: pass
                
        except Exception:
            # Catch-all to prevent main loop from crashing
            pass
            
        time.sleep(10)

if __name__ == "__main__":
    main()
