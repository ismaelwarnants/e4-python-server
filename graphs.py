"""
Standalone Graph Generator for E4 Data
Author: Modified for terminal selection & Enhanced EDA filtering
Date: 25/11/2025

Features:
1. Terminal-based numbered selection of session folders.
2. Generates graphs EXACTLY like the original server code.
3. FILTERS: 
    - Discards the first 250 samples of EDA data.
    - Removes any EDA values greater than 10 µS.
4. SAVES: Output as 'summary_graphs_updated.png'.
"""

import os
import sys
import pandas as pd
import matplotlib
# Use Agg backend to prevent popup windows, just save to file
matplotlib.use('Agg') 
import matplotlib.pyplot as plt

# Configuration
OUTPUT_DIR = 'output'
EDA_DISCARD_COUNT = 250
EDA_MAX_THRESHOLD = 10.0

def list_session_folders():
    """Finds all timestamped folders in the output directory."""
    if not os.path.exists(OUTPUT_DIR):
        print(f"Error: Directory '{OUTPUT_DIR}' not found.")
        return []

    # Get all subdirectories
    dirs = [d for d in os.listdir(OUTPUT_DIR) if os.path.isdir(os.path.join(OUTPUT_DIR, d))]
    dirs.sort()
    return dirs

def select_folder_terminal():
    """Terminal UI for selecting a folder by number."""
    folders = list_session_folders()
    
    if not folders:
        print("No session data found in 'output/'.")
        sys.exit()

    print("\n=== Available Sessions ===")
    for idx, folder in enumerate(folders):
        print(f"{idx + 1}. {folder}")
    print("==========================")

    while True:
        try:
            selection = input(f"Select a session number (1-{len(folders)}): ")
            idx = int(selection) - 1
            if 0 <= idx < len(folders):
                return os.path.join(OUTPUT_DIR, folders[idx])
            else:
                print("Invalid number. Please try again.")
        except ValueError:
            print("Please enter a valid number.")

def generate_graphs_updated(session_path):
    """Generates graphs with the specific EDA modification."""
    print(f"\nProcessing data in: {session_path}...")
    
    # Define files and titles exactly like original code
    files = {
        'BVP.csv': 'BVP', 
        'EDA.csv': 'EDA (µS)', 
        'TEMP.csv': 'Temperature (°C)', 
        'ACC.csv': 'Accelerometer (g)'
    }
    
    # Create plot layout
    fig, axs = plt.subplots(len(files), 1, figsize=(12, 16), constrained_layout=True)
    fig.suptitle(f'Empatica E4 Data Session: {os.path.basename(session_path)}', fontsize=16)

    for i, (filename, title) in enumerate(files.items()):
        filepath = os.path.join(session_path, filename)
        
        # Check if file exists and has data
        if os.path.exists(filepath) and os.path.getsize(filepath) > 10:
            try:
                # Read CSV (No header, as per original spec)
                df = pd.read_csv(filepath, header=None)
                
                # === MODIFICATION: EDA FILTERING ===
                if filename == 'EDA.csv':
                    original_count = len(df)
                    
                    # 1. Discard first 250 samples (Settling time)
                    if len(df) > EDA_DISCARD_COUNT:
                        df = df.iloc[EDA_DISCARD_COUNT:]
                    
                    # 2. Filter out peaks > 10 (Artifact removal)
                    # We keep only rows where the value (column 0) is <= 10
                    df = df[df[0] <= EDA_MAX_THRESHOLD]
                    
                    # Reset index so plot starts at 0 and connects cleanly
                    df = df.reset_index(drop=True)
                    
                    # Update title to reflect filters
                    title += f" (First {EDA_DISCARD_COUNT} cut, >{EDA_MAX_THRESHOLD}µS removed)"
                    print(f"-> EDA Filtered: {original_count} -> {len(df)} samples remaining.")
                # ===================================

                if filename == 'ACC.csv':
                    # ACC has 3 columns: X, Y, Z
                    axs[i].plot(df[0] / 64.0, label='X', alpha=0.7)
                    axs[i].plot(df[1] / 64.0, label='Y', alpha=0.7)
                    axs[i].plot(df[2] / 64.0, label='Z', alpha=0.7)
                    axs[i].legend()
                else:
                    # other files have 1 column
                    if not df.empty:
                        axs[i].plot(df[0])
                    else:
                        title += " (All data filtered out)"
                
                axs[i].set_title(title)
                axs[i].set_xlabel('Sample')
                axs[i].grid(True, alpha=0.3)
            except Exception as e:
                axs[i].set_title(f"Could not plot {title}: {e}")
                print(f"Error plotting {filename}: {e}")
        else:
            axs[i].set_title(f"{title} (No data collected)")

    # Save as [original_graph_name]_updated.png
    graph_output_path = os.path.join(session_path, 'summary_graphs_updated.png')
    
    try:
        plt.savefig(graph_output_path, dpi=150)
        print(f"SUCCESS: Graphs saved to: {graph_output_path}")
    except Exception as e:
        print(f"Error saving file: {e}")

if __name__ == "__main__":
    # check for dependencies
    try:
        import pandas
        import matplotlib
    except ImportError:
        print("Missing libraries. Please install: pip install pandas matplotlib")
        sys.exit()

    selected_path = select_folder_terminal()
    generate_graphs_updated(selected_path)