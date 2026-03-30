"""Build standalone executables using PyInstaller.

Usage:
    python build.py           # Build both monitor and agent
    python build.py monitor   # Build monitor only
    python build.py agent     # Build agent only
"""
import subprocess
import sys
import shutil
from pathlib import Path

HERE = Path(__file__).parent
DIST = HERE / "dist"
BUILD = HERE / "build"

def build_monitor():
    """Build the monitor executable."""
    print("Building ESL License Monitor...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "esl-license-monitor",
        "--icon", "NONE",
        "--add-data", f"esl_logo.png{';' if sys.platform == 'win32' else ':'}.",
        "--clean",
        str(HERE / "monitor.py"),
    ]
    subprocess.run(cmd, cwd=str(HERE), check=True)
    print(f"  -> {DIST / 'esl-license-monitor.exe'}")

def build_agent():
    """Build the agent executable."""
    print("Building ESL License Monitor Agent...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "esl-license-agent",
        "--icon", "NONE",
        "--clean",
        str(HERE / "agent.py"),
    ]
    subprocess.run(cmd, cwd=str(HERE), check=True)
    print(f"  -> {DIST / 'esl-license-agent.exe'}")

def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    
    if target in ("all", "monitor"):
        build_monitor()
    if target in ("all", "agent"):
        build_agent()
    
    # Copy supporting files to dist
    for f in ["README.md", "esl_logo.png"]:
        src = HERE / f
        if src.exists():
            shutil.copy2(src, DIST / f)
    
    # Create sample configs in dist
    if target in ("all", "agent"):
        sample_config = {
            "port": 9271,
            "host": "0.0.0.0",
            "token": "CHANGE-ME-GENERATE-WITH--generate-token",
            "logs_path": "C:\\ProgramData\\Parasoft\\DTP\\logs",
            "ssl_cert": "",
            "ssl_key": ""
        }
        import json
        (DIST / "agent_config.json.sample").write_text(json.dumps(sample_config, indent=2))
    
    if target in ("all", "monitor"):
        sample_servers = {
            "servers": [
                {"url": "http://dtp-server-1:9271", "token": "your-token-here", "name": "Production DTP"},
                {"url": "http://dtp-server-2:9271", "token": "your-token-here", "name": "Dev DTP"}
            ]
        }
        import json
        (DIST / "servers.json.sample").write_text(json.dumps(sample_servers, indent=2))
    
    print("\nBuild complete! Executables are in:", DIST)

if __name__ == "__main__":
    main()
