"""
Final implementation of the e4-python-server code.
Original author: github.com/ismaelwarnants

Modified by: github.com/mountainaught
Date: 05/10/2025

Thanks to ismaelwarnants for reverse engineering the E4's BLE stack and implementing the CSV.

Changes by myself:
    - Overhauled StreamProcessor, added __handle_bvp, __handle_gsr, etc.
    - Implemented Empatica's reverse engineered algos into the above
    - Minor calibration of sensor readings
    - More comments
"""

import argparse
import asyncio
import csv
import os
import struct
import time
from collections import deque
from datetime import datetime
from enum import Enum
from bleak import BleakClient, BleakScanner

# BLE characteristic UUIDs for the E4
DEVICE_NAME = "Empatica E4"
BVP_CHARACTERISTIC_UUID = "00003ea1-0000-1000-8000-00805f9b34fb"
GSR_CHARACTERISTIC_UUID = "00003ea8-0000-1000-8000-00805f9b34fb"
ACC_CHARACTERISTIC_UUID = "00003ea3-0000-1000-8000-00805f9b34fb"
ST_CHARACTERISTIC_UUID = "00003ea6-0000-1000-8000-00805f9b34fb"
CMD_CHARACTERISTIC_UUID = "00003e71-0000-1000-8000-00805f9b34fb"

# calibration values
TEMP_CALIB = 0.46

# coefficients and scale factors for measurements
FIR_COEF = [0.05, 0.1, 0.2, 0.3, 0.2, 0.1, 0.05]
BVP_SCALE_FACTOR = 10.0  # Adjust this based on your data


class DataType(Enum):
    """Enumeration of the different sensor types, useful for keeping StreamProcessor common"""
    ACC = "Accelerometer"  # 3-axis accelerometer
    BVP = "Blood Volume Pulse"  # Photoplethysmography signal
    GSR = "Galvanic Skin Response"  # Electrodermal Activity
    ST = "Skin Temperature"  # In degrees Celcius


class DataManager:
    """
    Simple file manager. All four sensors need to have their values written to a
    CSV file. One common manager is used across all files.
    """

    def __init__(self):
        self.session_path = ""
        self.writers = {}
        self.files = {}
        self.create_session_folder()

    # Creates a timestamped folder
    def create_session_folder(self):
        if not os.path.exists('output'):
            os.makedirs('output')
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.session_path = os.path.join('output', timestamp)
        os.makedirs(self.session_path)
        print(f"Saving data to: {self.session_path}")

    # Create sensor-specific file
    def setup_file(self, filename):
        filepath = os.path.join(self.session_path, filename)
        self.files[filename] = open(filepath, 'w', newline='')
        self.writers[filename] = csv.writer(self.files[filename])

    # Write data to sensor-specific file
    def write_data(self, filename, data_row):
        if filename in self.writers:
            self.writers[filename].writerow(data_row)

    # Save and close all files
    def close_files(self):
        for f in self.files.values():
            f.close()
        print("CSV files saved and closed.")


class StreamProcessor:
    """
    The primary logic of this program. When the E4 returns sensor readings as a BLE packet
    the sensor's corresponding StreamProcessor.process_packet is called. Depending on the
    datatype different parsing operations are done and returned.

    Important attributes:
        self.datatype (DataType): the type of sensor
        self.print_mode (boolean): print processed data to terminal
        self.data_manager (DataManager): data manager, saves outputs to CSV if provided
    """

    def __init__(self, name, datatype, filename, data_manager=None, print_mode=False):
        self.name = name
        self.datatype = datatype
        self.filename = filename
        self.data_manager = data_manager
        self.print_mode = print_mode
        self.first_packet = True

        # BVP sensor-specific state variables
        if datatype == DataType.BVP:
            self._bvp_green_offset = 0
            self._bvp_red_offset = 0
            self._fir1_buffer = deque([0.0] * len(FIR_COEF), maxlen=len(FIR_COEF))
            self._fir2_buffer = deque([0.0] * len(FIR_COEF), maxlen=len(FIR_COEF))
            self._fir3_buffer = deque([0.0] * len(FIR_COEF), maxlen=len(FIR_COEF))
            self._kalman_p = 1.0  # Error covariance
            self._kalman_x = 0.0  # Estimated state
            self._kalman_q = 0.01  # Process noise
            self._kalman_r = 0.1  # Measurement noise

    def process_packet(self, data):
        """Calls the correct handler according to datatype, then saves the file if so desired."""
        parsed_data = None

        # first parse data by the correct data type
        match self.datatype:
            case DataType.ACC:
                parsed_data = self.__handle_acc(data)
            case DataType.BVP:
                parsed_data = self.__handle_bvp(data)
            case DataType.GSR:
                parsed_data = self.__handle_gsr(data)
            case DataType.ST:
                parsed_data = self.__handle_temp(data)
            case _:
                return

        # skip if no data parsed
        if parsed_data is None:
            return

        # create file on first valid packet
        if self.first_packet and self.data_manager:
            try:
                self.data_manager.setup_file(self.filename)
                self.first_packet = False
            except Exception as ex:
                print(f"Error setting up {self.filename}: {ex}")
                return

        if self.data_manager:  # if the user chooses data saving and/or graphing
            if self.datatype == DataType.ACC:  # acc readings are stored as tuples: [(x1,y1,z1), (x2,y2,z2), ...]
                for reading in parsed_data:
                    self.data_manager.write_data(self.filename, [reading[0], reading[1], reading[2]])
            else:  # otherwise parsed_data is a normal array
                for value in parsed_data:
                    # write each value as a single-column row
                    self.data_manager.write_data(self.filename, [value])

    def __handle_bvp(self, data):
        """
        Process BVP packet. The E4 sends BVP measurements as 20 byte packets,
        using 7-bit packed delta encoding, 11 samples in each channel (red and green).
        Flow: Decode → Parse → FIR1 → FIR2 → Kalman → FIR3 → Output

        Side note: This one section took a week of reverse-engineering
        and hours of decompiling Empatica's code to implement.
        US$1500 "Proprietary Algorithm" right here.
        """
        if len(data) < 20:
            return None

        # ===== Stage 1: Decode =====
        # note: the variable names here make no sense because i copied them from a decompiled java library
        decoded = []
        uVar28 = 0

        # i have no clue what this loop does other than decode the raw packet
        # original call: PacketHandler_handlePacketForE4(byte *param_1,uint *param_2,undefined4 param_3)
        for uVar37 in range(0x14):  # 0x14 => 20 byte packet
            bVar21 = data[uVar37]
            iVar31 = uVar37 % 7
            uVar36 = iVar31 + 1

            uVar28 = (bVar21 >> uVar36) | uVar28

            output_val = uVar28 & 0x7F
            if output_val & 0x40:
                output_val |= 0x80
            if output_val > 127:
                output_val -= 256
            decoded.append(output_val)

            mask = (1 << uVar36) - 1
            uVar28 = ((bVar21 & mask) << (6 - iVar31)) & 0xFF

            if uVar36 == 7:
                output_val = uVar28 & 0x7F
                if output_val & 0x40:
                    output_val |= 0x80
                if output_val > 127:
                    output_val -= 256
                decoded.append(output_val)
                uVar28 = 0

        final_val = data[0x13] & 0x3F
        if final_val & 0x20:
            final_val |= 0xC0
        if final_val > 127:
            final_val -= 256
        decoded.append(final_val)

        # ===== Stage 2: Parse green/red pairs & Process through filter chain =====
        # this is where the magical parsing pipeline happens. stage 2 encapsulates four filter stages
        # and a boatload of processing. awesome.

        bvp_readings = []
        for i in range(min(11, len(decoded) // 2)):
            green = decoded[i * 2]
            red = decoded[i * 2 + 1]

            # Update offsets
            self._bvp_green_offset += red
            self._bvp_red_offset += green

            # ===== Stage 3: FIR Filter 1 - red channel =====
            # original call: FirFilter_filter(param_2, (undefined8 *)(param_4 + 0xc))
            self._fir1_buffer.append(float(red))
            filtered_red = sum(c * s for c, s in zip(FIR_COEF, self._fir1_buffer))

            # ===== Stage 4: FIR Filter 2 - Filter weighted combination =====
            # original call: FirFilter_filter((param_2 + param_1 * 10.0) / 11.0, (undefined8 *)(param_4 + 0xe))
            weighted = (red + green * 10.0) / 11.0
            self._fir2_buffer.append(weighted)
            filtered_weighted = sum(c * s for c, s in zip(FIR_COEF, self._fir2_buffer))

            # ===== Stage 5: Kalman Filter - Combine both filtered signals =====
            # original call: KalmanFilter_evaluate(uVar4, uVar5, (undefined8 *)(param_4 + 0x12))
            kalman_out = self._kalman_filter(filtered_red, filtered_weighted)

            # ===== Stage 6: FIR Filter 3 - Final smoothing =====
            # original call: FirFilter_filterAndSum(uVar8, -(float)uVar8, (undefined8 *)(param_4 + 0x10))
            # note: filterAndSum does filter(x) + filter(-x), but we'll simplify
            self._fir3_buffer.append(kalman_out)
            filtered_kalman = sum(c * s for c, s in zip(FIR_COEF, self._fir3_buffer))

            # ===== Stage 7: Return final value =====
            bvp = round(-filtered_kalman * BVP_SCALE_FACTOR, 2)  # scaling and rounding
            bvp_readings.append(bvp)

        if bvp_readings and self.print_mode:
            print(f"BVP: {bvp_readings}")

        return bvp_readings if bvp_readings else None

    def _kalman_filter(self, measurement1, measurement2):
        """
        Simplified Kalman filter that fuses two measurements.
        Based on KalmanFilter_evaluate() from decompiled code.

        The original is way too complex with adaptive covariance based on thresholds,
        but the core idea is: combine two sensor readings optimally.
        """
        # average the two measurements as the observation
        measurement = (measurement1 + measurement2) / 2.0

        # prediction step
        # x_pred = x (state doesn't change, we're just filtering)
        p_pred = self._kalman_p + self._kalman_q

        # Update step
        kalman_gain = p_pred / (p_pred + self._kalman_r)  # kalman gain

        self._kalman_x = self._kalman_x + kalman_gain * (measurement - self._kalman_x)  # update estimate

        self._kalman_p = (1 - kalman_gain) * p_pred  # update error covariance

        # adaptive covariance (simplified from decompiled threshold logic)
        # original checks if changes are large (>80 or >540) to increase trust
        diff1 = abs(measurement1 - measurement2)
        if diff1 > 20:  # if signals diverge, increase uncertainty
            self._kalman_p = min(self._kalman_p * 1.2, 10.0)
        else:  # if signals agree, decrease uncertainty
            self._kalman_p = max(self._kalman_p * 0.95, 0.01)

        return self._kalman_x

    def __handle_gsr(self, data):
        """
        Processes Galvanic Skin Response, aka Electrodermal Activity (EDA) measurements.
        E4 sends EDA as 20 bytes packets, using 24-bit (3-byte) big endian encoding for 6 samples across 18 bytes.
        Last 2 bytes are used as a packet counter.

        Really nothing crazy going on here.
        """

        # if packet is empty, return
        if len(data) < 20:
            return None

        i = 0
        readings = []

        # go through the data three bytes at a time
        while i + 3 <= len(data) - 2:
            byte1 = data[i]
            byte2 = data[i + 1]
            byte3 = data[i + 2]

            raw_value = (byte1 << 16) | (byte2 << 8) | byte3  # combine bytes into raw value
            eda_microsiemens = 1000000.0 / raw_value if raw_value > 0 else 0  # simple conversion into µS

            readings.append(eda_microsiemens)  # add to the return array
            i += 3

        if readings:
            avg_eda = sum(readings) / len(readings)
            if self.print_mode:
                print(f"EDA: {avg_eda:.3f} µS")
            return readings
        return None

    def __handle_temp(self, data):
        """
        Processes Skin Temperature. E4 sends ST as 12 byte packets, using unsigned 16-bit (2-byte) Big Endian encoding
        for 4 samples across 8 bytes. Last 4 bytes are used for metadata.
        """

        # return if data empty
        if len(data) < 12:
            return None

        i = 0
        temp_readings = []
        while i < 8:
            raw = struct.unpack_from('<H', data, i)[0]  # use struct to decode the MSB data format
            temp = ((raw * 0.02) - 276.0) + TEMP_CALIB  # convert from Kelvin to Celsius and add calibration

            temp_readings.append(temp)
            i += 2

        if temp_readings:
            avg_temp = sum(temp_readings) / len(temp_readings)
            if self.print_mode:
                print(f"Temperature: {avg_temp:.2f}°C")
            return temp_readings
        return None

    def __handle_acc(self, data):
        """
        Processes Accelerometer. Not too sure about the stats on this one I got this code from the original script.
        Three axis in each reading. etc.
        """
        i = 0
        acc_readings = []

        while i + 3 <= len(data):
            try:
                x, y, z = struct.unpack_from('<bbb', data, i)  # struct for decoding
                acc_readings.append((x, y, z))
                i += 3
            except struct.error:
                break

        if acc_readings:
            # average out all three axis movements
            avg_acc = tuple(sum(col) / len(col) for col in zip(*acc_readings))
            x = avg_acc[0]
            y = avg_acc[1]
            z = avg_acc[2]
            if self.print_mode:
                print(f"Accelerometer: X: {x / 64.0:.2f}g, Y: {y / 64.0:.2f}g, Z: {z / 64.0:.2f}g")
            return acc_readings
        return None


def generate_graphs_from_csv(session_path):
    """Reads data from CSV files, generates plots, and saves them to a file."""
    print("Generating graphs from saved data...")
    try:
        import pandas as pd
        import matplotlib
        # use a non-interactive backend to be safe
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        print("\nCould not import pandas or matplotlib. Please install with: pip install pandas matplotlib")
        return

    files = {'BVP.csv': 'BVP', 'EDA.csv': 'EDA (µS)', 'TEMP.csv': 'Temperature (°C)', 'ACC.csv': 'Accelerometer (g)'}
    fig, axs = plt.subplots(len(files), 1, figsize=(12, 16), constrained_layout=True)
    fig.suptitle(f'Empatica E4 Data Session: {os.path.basename(session_path)}', fontsize=16)

    for i, (filename, title) in enumerate(files.items()):
        filepath = os.path.join(session_path, filename)
        if os.path.exists(filepath) and os.path.getsize(filepath) > 10:
            try:
                df = pd.read_csv(filepath, header=None)
                if filename == 'ACC.csv':
                    # ACC has 3 columns: X, Y, Z
                    axs[i].plot(df[0] / 64.0, label='X', alpha=0.7)
                    axs[i].plot(df[1] / 64.0, label='Y', alpha=0.7)
                    axs[i].plot(df[2] / 64.0, label='Z', alpha=0.7)
                    axs[i].legend()
                else:
                    # other files have 1 column
                    axs[i].plot(df[0])
                axs[i].set_title(title)
                axs[i].set_xlabel('Sample')
                axs[i].grid(True, alpha=0.3)
            except Exception as e:
                axs[i].set_title(f"Could not plot {title}: {e}")
        else:
            axs[i].set_title(f"{title} (No data collected)")

    graph_output_path = os.path.join(session_path, 'summary_graphs.png')
    plt.savefig(graph_output_path, dpi=150)
    print(f"Graphs saved to: {graph_output_path}")


async def main_ble_loop(args, data_manager):
    """The main asynchronous part of the program."""
    print(f"Scanning for {DEVICE_NAME}...")
    device = await BleakScanner.find_device_by_name(DEVICE_NAME)
    if not device:
        print(f"Could not find a device named {DEVICE_NAME}")
        return
    print(f"Found {DEVICE_NAME} with address {device.address}. Connecting...")

    # processor for each sensor type
    bvp_processor = StreamProcessor("BVP", DataType.BVP, "BVP.csv", data_manager, args.print)
    gsr_processor = StreamProcessor("GSR", DataType.GSR, "EDA.csv", data_manager, args.print)
    temp_processor = StreamProcessor("Temp", DataType.ST, "TEMP.csv", data_manager, args.print)
    acc_processor = StreamProcessor("ACC", DataType.ACC, "ACC.csv", data_manager, args.print)

    async with BleakClient(device) as client:
        if not client.is_connected:
            print("Failed to connect.")
            return
        print(f"Connected to {DEVICE_NAME}\nInitializing...")

        # these tell the code what function to run when the E4 replies with a given characteristic (sensor reading)
        await client.start_notify(BVP_CHARACTERISTIC_UUID, lambda s, d: bvp_processor.process_packet(d))
        await client.start_notify(GSR_CHARACTERISTIC_UUID, lambda s, d: gsr_processor.process_packet(d))
        await client.start_notify(ST_CHARACTERISTIC_UUID, lambda s, d: temp_processor.process_packet(d))
        await client.start_notify(ACC_CHARACTERISTIC_UUID, lambda s, d: acc_processor.process_packet(d))

        # tell the E4 to start streaming sensor readings by sending the command
        command = struct.pack('<BI', 1, int(time.time()))
        await client.write_gatt_char(CMD_CHARACTERISTIC_UUID, command)

        print("\n--- Data Streaming Started ---")
        print("Press Ctrl+C to disconnect and stop.")

        while True:
            await asyncio.sleep(1)  # go indefinitely


if __name__ == "__main__":
    # all the parsable options
    parser = argparse.ArgumentParser(description="Connect, stream, and save data from an Empatica E4.")
    parser.add_argument('--save', action='store_true', help="Save sensor data to CSV files in a timestamped folder.")
    parser.add_argument('--print', action='store_true', help="Print sensor data to the console in real-time.")
    parser.add_argument('--graph', action='store_true',
                        help="Generate and save graphs from data after the session ends. Requires --save.")
    args = parser.parse_args()

    if args.graph and not args.save:
        parser.error("--graph requires --save to be enabled.")

    # one data manager to rule them all, and in the darkness bind them
    data_manager = DataManager() if args.save else None

    try:
        asyncio.run(main_ble_loop(args, data_manager))
    except KeyboardInterrupt:
        print("\nProgram stopped by user.")
    except Exception as e:
        print(f"An error occurred in the main loop: {e}")
    finally:
        if data_manager:
            data_manager.close_files()
            if args.graph:
                generate_graphs_from_csv(data_manager.session_path)
