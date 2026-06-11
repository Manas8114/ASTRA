import subprocess
import sys
import os
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

def run_script(script_path: str):
    logging.info(f"Running {script_path}...")
    try:
        # Use sys.executable to ensure we use the current virtualenv's python
        subprocess.run([sys.executable, script_path], check=True, text=True)
        logging.info(f"Successfully completed {script_path}.")
    except subprocess.CalledProcessError:
        logging.error(f"Error running {script_path}. Exiting.")
        sys.exit(1)

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(base_dir)

    scripts = [
        "training/generate_normal_data.py",
        "training/train_lstm.py",
        "training/train_forecast.py",
        "training/export_onnx.py",
    ]

    for script in scripts:
        if not os.path.exists(script):
            logging.error(f"Script not found: {script}")
            sys.exit(1)
        run_script(script)
        
    logging.info("All model training scripts completed successfully.")

if __name__ == "__main__":
    main()
