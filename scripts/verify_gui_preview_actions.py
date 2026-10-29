import os
import time
import subprocess
import json

def run_xdo(cmd):
    full_cmd = ["docker", "exec", "-e", "DISPLAY=:99", "test-gui-container", "bash", "-c", cmd]
    return subprocess.run(full_cmd, capture_output=True, text=True, check=True)

def capture_screenshot(filename, step_name):
    print(f"[*] Step: {step_name} -> {filename}")
    run_xdo(f"scrot /tmp/{filename}")
    host_path = os.path.join("docs", "gui_preview_evidence", filename)
    os.makedirs(os.path.dirname(host_path), exist_ok=True)
    subprocess.run(["docker", "cp", f"test-gui-container:/tmp/{filename}", host_path], check=True)
    size = os.path.getsize(host_path)
    print(f"    Saved: {host_path} ({size:,} bytes)")
    return host_path

def main():
    print("==========================================================================")
    print("  AUTOMATED VERIFICATION OF SWING TodoApp GUI IN DOCKER SANDBOX")
    print("==========================================================================")

    # 1. Capture initial state
    capture_screenshot("01_initial_gui.png", "Initial GUI Window")
    time.sleep(0.5)

    # 2. Add Task 1: "Buy fresh groceries"
    print("\n[*] [ACTION: ADD] Typing Task 1 into text field and clicking 'Add'...")
    run_xdo("xdotool mousemove 576 218 click 1")
    time.sleep(0.3)
    run_xdo("xdotool type --delay 50 'Buy fresh groceries'")
    time.sleep(0.3)
    run_xdo("xdotool mousemove 298 543 click 1")
    time.sleep(0.8)
    capture_screenshot("02_task1_added.png", "Task 1 Added to List")

    # 3. Add Task 2: "Implement noVNC GUI preview"
    print("\n[*] [ACTION: ADD] Typing Task 2 into text field and clicking 'Add'...")
    run_xdo("xdotool mousemove 576 218 click 1")
    time.sleep(0.3)
    run_xdo("xdotool type --delay 50 'Implement noVNC GUI preview'")
    time.sleep(0.3)
    run_xdo("xdotool mousemove 298 543 click 1")
    time.sleep(0.8)
    capture_screenshot("03_task2_added.png", "Task 2 Added to List")

    # 4. Edit Task 1:
    print("\n[*] [ACTION: EDIT] Selecting Task 1 and clicking 'Edit'...")
    run_xdo("xdotool mousemove 350 265 click 1")
    time.sleep(0.4)
    run_xdo("xdotool mousemove 367 543 click 1")
    time.sleep(1.0)
    capture_screenshot("04_edit_dialog_open.png", "Edit Dialog (JOptionPane Popup)")

    print("[*] Submitting updated description: 'Buy fresh organic groceries'...")
    run_xdo("xdotool key --delay 50 ctrl+a BackSpace")
    time.sleep(0.3)
    run_xdo("xdotool type --delay 50 'Buy fresh organic groceries'")
    time.sleep(0.4)
    run_xdo("xdotool key Return")
    time.sleep(0.8)
    capture_screenshot("05_after_edit_applied.png", "Task 1 Description Updated")

    # 5. Complete Task 1:
    print("\n[*] [ACTION: COMPLETE] Selecting Task 1 and clicking 'Complete'...")
    run_xdo("xdotool mousemove 350 265 click 1")
    time.sleep(0.4)
    run_xdo("xdotool mousemove 456 543 click 1")
    time.sleep(0.8)
    capture_screenshot("06_task1_completed.png", "Task 1 Marked as Completed [x]")

    # 6. Clear Completed:
    print("\n[*] [ACTION: CLEAR COMPLETED] Clicking 'Clear Completed' button...")
    run_xdo("xdotool mousemove 679 543 click 1")
    time.sleep(0.8)
    capture_screenshot("07_after_clear_completed.png", "Completed Task 1 Cleared")

    # 7. Delete Task 2:
    print("\n[*] [ACTION: DELETE] Selecting remaining task and clicking 'Delete'...")
    run_xdo("xdotool mousemove 350 265 click 1")
    time.sleep(0.4)
    run_xdo("xdotool mousemove 555 543 click 1")
    time.sleep(0.8)
    capture_screenshot("08_after_delete_task.png", "Remaining Task Deleted (List Empty)")

    print("\n[✓] All 5 button actions demonstrated with captured visual evidence!")

if __name__ == "__main__":
    main()
