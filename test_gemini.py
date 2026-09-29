import os
import sys
import subprocess

def test_gemini_cli():
    print("Testing Gemini CLI...")
    cmd = ["cmd.exe", "/c", "set PATH=C:\\Program Files\\nodejs;C:\\Users\\Onlys\\AppData\\Roaming\\npm;%PATH% && gemini --version"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    print("Gemini CLI Version:", result.stdout.strip())
    return result.returncode == 0

if __name__ == "__main__":
    success = test_gemini_cli()
    sys.exit(0 if success else 1)
