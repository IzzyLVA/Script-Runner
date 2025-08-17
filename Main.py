import os
import subprocess
import threading
import queue
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

PRELOADED = {
    "Windows Config Script": (
        "Win10.bat",
        r"""@echo off
setlocal enabledelayedexpansion

echo Welcome to the System Configuration Script

:: Check for admin rights
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Access Denied. Please run the script with administrator privileges.
    pause
    exit /b 1
)

:: Logging setup
set logFile=C:\config_script_log.txt
echo [%date% %time%] Starting script execution >> %logFile%

:menu
cls
echo Welcome to the System Configuration Script
echo Options:
echo "1) Set user properties      2) Create a user"
echo "3) Disable a user           4) Change all passwords"
echo "5) Disable guest/admin      6) Set password policy"
echo "7) Password Policy 2        8) Group check status"
echo "9) Set lockout policy       10) Enable Firewall"
echo "11) Search for media files  12) Disable services"
echo "13) Turn on UAC             14) Remote Desktop Config"
echo "15) Enable auto update       16) Security options"
echo "17) Audit the machine        18) Auto Login netpwiz"
echo "19) Disable port 1900        20) Adaptor Settings"
echo "21) Windows Services         22) Disable Tiles"
echo "23) Disable AutoPlay         0) Exit"
echo "70) Reboot"

set /p answer=Please choose an option: 
if "%answer%"=="0" exit /b
goto :menu
"""
    ),
    "Linux Security Script": (
        "Linux.sh",
        r"""#!/bin/bash

if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root"
   exit 1
fi

LOGFILE="/var/log/security_script.log"
exec > >(tee -i "$LOGFILE") 2>&1
echo "Script started at $(date)"

# 1. Set minimum password length
echo "Setting minimum password length to 8..."
cp /etc/pam.d/common-password /etc/pam.d/common-password.bak || exit 1
sed -i 's/pam_unix.so/& minlen=8/' /etc/pam.d/common-password || exit 1
echo "Minimum password length set."

# 2. Disable null passwords
echo "Disabling null passwords..."
cp /etc/pam.d/common-auth /etc/pam.d/common-auth.bak || exit 1
sed -i '/nullok/d' /etc/pam.d/common-auth || exit 1
echo "Null passwords are now disabled."

# 3. Enable UFW
echo "Enabling UFW..."
ufw enable || exit 1

# 4. Install X2GO
apt-get update && apt-get install -y x2goserver || exit 1

# 5. Disable Nginx
systemctl stop nginx || true
systemctl disable nginx || exit 1

# 6. Daily updates
cat <<EOF > /etc/apt/apt.conf.d/10periodic
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

# 7. Disable SSH root login
cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak || exit 1
sed -i 's/^PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config || exit 1
systemctl restart sshd || exit 1

echo "All tasks completed successfully at $(date)."
"""
    ),
}


class ScriptRunnerApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Script Runner")
        self.geometry("800x600")
        self.configure(bg="black")

        self.accent = "#00ffff"

        os.makedirs("scripts", exist_ok=True)

        self.scripts = {}
        for name, (filename, content) in PRELOADED.items():
            path = os.path.join("scripts", filename)
            if not os.path.exists(path):
                with open(path, "w", newline="\n") as f:
                    f.write(content)
                if filename.endswith(".sh"):
                    try:
                        os.chmod(path, 0o755)
                    except Exception:
                        pass
            self.scripts[name] = path

        self.frames = {}
        for F in (SelectionPage, RunnerPage):
            page = F(self)
            self.frames[F] = page
            page.grid(row=0, column=0, sticky="nsew")

        self.show_frame(SelectionPage)

    def show_frame(self, page):
        frame = self.frames[page]
        frame.tkraise()

    def add_script(self):
        filepath = filedialog.askopenfilename(
            filetypes=[("Batch or Bash files", "*.bat *.sh")]
        )
        if filepath:
            name = os.path.basename(filepath)
            if filepath.endswith(".sh"):
                try:
                    os.chmod(filepath, 0o755)
                except Exception:
                    pass
            self.scripts[name] = filepath
            self.frames[SelectionPage].update_scripts()

    def run_script(self, script_name):
        script_path = self.scripts[script_name]
        self.frames[RunnerPage].run_and_display(script_name, script_path)
        self.show_frame(RunnerPage)


class SelectionPage(tk.Frame):
    def __init__(self, controller):
        super().__init__(controller, bg="black")
        self.controller = controller

        tk.Label(self, text="Available Scripts", font=("VT323", 24),
                 bg="black", fg=controller.accent).pack(pady=10)

        self.script_var = tk.StringVar(self)
        self.script_menu = tk.OptionMenu(self, self.script_var, ())
        self.script_menu.config(bg="black", fg=controller.accent, width=50, highlightthickness=0)
        self.script_menu["menu"].config(bg="black", fg=controller.accent)
        self.script_menu.pack(pady=10)

        tk.Button(self, text="Add Script", command=controller.add_script,
                  bg="black", fg=controller.accent).pack(pady=10)

        tk.Button(self, text="Run Script", command=self.run_selected,
                  bg="black", fg=controller.accent).pack(pady=10)

        tk.Label(self, text="Made by IzzyLVA", font=("VT323", 15),
                 bg="black", fg=controller.accent).pack(side="bottom", pady=8)

        self.update_scripts()

    def update_scripts(self):
        menu = self.script_menu["menu"]
        menu.delete(0, "end")
        for name in self.controller.scripts.keys():
            menu.add_command(label=name, command=lambda value=name: self.script_var.set(value))
        if not self.script_var.get():
            keys = list(self.controller.scripts.keys())
            if keys:
                self.script_var.set(keys[0])

    def run_selected(self):
        choice = self.script_var.get()
        if not choice:
            messagebox.showwarning("No script selected", "Please choose a script to run.")
            return
        self.controller.run_script(choice)


class RunnerPage(tk.Frame):
    def __init__(self, controller):
        super().__init__(controller, bg="black")
        self.controller = controller
        self.process = None
        self.output_queue = queue.Queue()

        self.title_label = tk.Label(self, text="", font=("VT323", 22),
                                    bg="black", fg=controller.accent)
        self.title_label.pack(pady=10)

        self.output_box = scrolledtext.ScrolledText(self, wrap=tk.WORD,
                                                    bg="black", fg=controller.accent,
                                                    insertbackground=controller.accent,
                                                    width=95, height=24)
        self.output_box.pack(pady=10)

        input_row = tk.Frame(self, bg="black")
        input_row.pack(pady=4)
        tk.Label(input_row, text="Input:", bg="black", fg=controller.accent).pack(side="left")
        self.input_entry = tk.Entry(input_row, bg="black", fg=controller.accent,
                                    insertbackground=controller.accent, width=20)
        self.input_entry.pack(side="left", padx=(6, 6))
        self.input_entry.bind("<Return>", lambda e: self.send_input())
        tk.Button(input_row, text="Send", command=self.send_input,
                  bg="black", fg=controller.accent).pack(side="left")

        btn_row = tk.Frame(self, bg="black")
        btn_row.pack(pady=8)
        tk.Button(btn_row, text="Clear Output", command=self.clear_output,
                  bg="black", fg=controller.accent).pack(side="left", padx=6)
        tk.Button(btn_row, text="Stop & Back", command=self.stop_and_return,
                  bg="black", fg=controller.accent).pack(side="left", padx=6)

        # Footer
        tk.Label(self, text="Made by izzylva", font=("VT323", 15),
                 bg="black", fg=controller.accent).pack(side="bottom", pady=8)

    def append_output(self, text):
        self.output_box.insert(tk.END, text)
        self.output_box.see(tk.END)
        self.update_idletasks()

    def run_and_display(self, script_name, script_path):
        self.title_label.config(text=f"Running: {script_name}")
        self.output_box.delete("1.0", tk.END)
        self.input_entry.delete(0, tk.END)

        try:
            if script_path.endswith(".bat"):
                self.process = subprocess.Popen(
                    ["cmd.exe", "/c", script_path],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1
                )
            elif script_path.endswith(".sh"):
                self.process = subprocess.Popen(
                    ["bash", script_path],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1
                )
            else:
                self.append_output("Unsupported file type\n")
                return

            threading.Thread(target=self._enqueue_output, daemon=True).start()
            self.after(100, self._poll_output)

        except Exception as e:
            self.append_output(f"Execution Error: {e}\n")

    def _enqueue_output(self):
        for line in self.process.stdout:
            self.output_queue.put(line)
        self.process.stdout.close()

    def _poll_output(self):
        try:
            while True:
                line = self.output_queue.get_nowait()
                self.append_output(line)
        except queue.Empty:
            pass

        if self.process and self.process.poll() is None:
            self.after(100, self._poll_output)

    def send_input(self):
        if self.process and self.process.stdin and self.process.poll() is None:
            text = self.input_entry.get()
            self.input_entry.delete(0, tk.END)
            try:
                self.process.stdin.write(text + "\n")
                self.process.stdin.flush()
            except Exception as e:
                self.append_output(f"\n[stdin error] {e}\n")

    def clear_output(self):
        self.output_box.delete("1.0", tk.END)

    def stop_and_return(self):
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
        self.process = None
        self.controller.show_frame(SelectionPage)


if __name__ == "__main__":
    app = ScriptRunnerApp()
    app.mainloop()
