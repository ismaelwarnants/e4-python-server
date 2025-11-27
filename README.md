# Empatica E4 Python Server

#### This is a fork of the original E4 python server script made by [@ismaelwarnants](https://github.com/ismaelwarnants).

The data parsing methods were modified to match the E4's outputted data types and calibrated to produce (mostly) accurate results. 

Most of it was obtained through laborious reverse-engineering so if there are any issues (or you want to praise me :3) don't hesitate to contact me [here](mailto:e.t.unal@se23.qmul.ac.uk).

### Original Readme
This project provides a Python script to connect to an Empatica E4 wristband via Bluetooth LE, stream physiological data in real-time, and save it for analysis. It is a lightweight, command-line tool designed for researchers and developers who need direct access to raw E4 data **without relying on Empatica's official software**.

## Features

  * **Direct BLE Connection**: Connects directly to any nearby Empatica E4 device.
  * **Real-time Data Streaming**: Captures BVP, GSR (EDA), Accelerometer, and Temperature data.
  * **Console Output**: Print live sensor data directly to the terminal for monitoring.
  * **CSV Data Logging**: Save complete session data into timestamped folders, with each sensor's data in a separate `.csv` file.
  * **Post-Session Graphing**: Automatically generate and save a summary image with plots of all sensor data from a saved session.

## Requirements

  * Python 3.8+
  * A Bluetooth-enabled computer (tested on Ubuntu 24.04 LTS)
  * An Empatica E4 device

## Usage with `uv`
### Installation

1.  **Install `uv`:**
    The recommended way to install `uv` is using its standalone installers.

      * On **macOS** and **Linux**:
        ```bash
        curl -LsSf https://astral.sh/uv/install.sh | sh
        ```
      * On **Windows**:
        ```powershell
        powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
        ```

2.  **Clone the Repository:**

    ```bash
    git clone https://github.com/ismaelwarnants/e4-python-server.git
    cd e4-python-server
    ```

3.  **Create the Virtual Environment and Install Dependencies:**
    `uv` will create a local virtual environment (`.venv`) and install all the packages listed in `pyproject.toml`.

    ```bash
    # This single command creates the .venv folder and installs everything.
    uv sync
    ```

4.  **(Ubuntu/Debian) Install Tkinter:**
    The graphing functionality depends on the Tkinter GUI toolkit, which is a system-level package.

    ```bash
    sudo apt-get update
    sudo apt-get install python3-tk
    ```

### Activating the Environment

Before running the script, you must first activate the virtual environment created by `uv`.

  * On **macOS** and **Linux**:
    ```bash
    source .venv/bin/activate
    ```
  * On **Windows**:
    ```powershell
    .venv\Scripts\activate
    ```

You'll know the environment is active when you see `(.venv)` at the beginning of your terminal prompt.

### Running the Script

Once the environment is activated, you can run the `main.py` script using the standard `python` command.

> **Note on `uv run`**: The `uv run` command is designed for running tools like formatters or linters without activating the environment. For a long-running application like this one, especially one that may generate graphical plots, the most reliable method is to activate the environment first and then use the standard `python` command.

  * **To Print Data to Console:**

    ```bash
    python main.py --print
    ```

  * **To Save Data to CSVs:**

    ```bash
    python main.py --save
    ```

  * **To Save Data and Also Print it:**

    ```bash
    python main.py --save --print
    ```

  * **To Save Data and Generate Graphs at the End:**

    ```bash
    python main.py --save --graph
    ```

### Deactivating the Environment

When you're finished, you can deactivate the virtual environment.

```bash
deactivate
```

## Output File Structure

When using the `--save` option, your `output` directory will be populated as follows:

```
output/
└── 2025-10-21_21-30-00/      <-- Session Folder
    ├── ACC.csv             <-- 3-axis Accelerometer data (raw integer values)
    ├── BVP.csv             <-- Blood Volume Pulse data
    ├── EDA.csv             <-- Electrodermal Activity data (in µS)
    ├── TEMP.csv            <-- Temperature data (in °C)
    └── summary_graphs.png  <-- (Optional) Generated if --graph is used
```

The format of the `.csv` files is designed to be compatible with standard data analysis tools.
