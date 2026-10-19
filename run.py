import subprocess
import sys
import time
import os

def main():
    print("Starting HSE Management System...")
    
    # Get the paths to the apps relative to this script
    base_dir = os.path.dirname(os.path.abspath(__file__))
    flask_app_path = os.path.join(base_dir, "data_entry_app", "app.py")
    streamlit_app_path = os.path.join(base_dir, "dashboard_app", "dashboard.py")

    # Apply schema migrations before launching either application.
    sys.path.insert(0, base_dir)
    from database.init_db import initialize_database
    initialize_database()

    # Use the current Python executable to avoid path/environment issues
    python_exe = sys.executable

    try:
        # 1. Start Flask App (Data Entry)
        print("Launching Data Entry Portal (Flask)...")
        flask_process = subprocess.Popen([python_exe, flask_app_path])

        # Give Flask a brief moment to initialize
        time.sleep(2)

        # 2. Start Streamlit Dashboard
        # Using 'python -m streamlit' to prevent the command not found error you experienced earlier
        print("Launching Real-Time Dashboard (Streamlit)...")
        streamlit_process = subprocess.Popen([python_exe, "-m", "streamlit", "run", streamlit_app_path])

        print("\n====================================================")
        print("✅ Both applications are running!")
        print("📝 Data Entry Portal: http://localhost:5000")
        print("📊 Live Dashboard:    http://localhost:8501")
        print("====================================================")
        print("Press Ctrl+C in this terminal to stop both servers.\n")
        
        # Keep the script running to monitor the background processes
        flask_process.wait()
        streamlit_process.wait()

    except KeyboardInterrupt:
        # Handle graceful shutdown when you press Ctrl+C
        print("\nShutting down both servers...")
        flask_process.terminate()
        streamlit_process.terminate()
        print("Servers stopped successfully.")

if __name__ == '__main__':
    main()