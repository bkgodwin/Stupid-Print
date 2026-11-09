# Stupid Print

Stupid Print is a Python desktop label studio for the Phomemo D30 family. It designs and previews monochrome thermal labels and prints directly over Bluetooth Classic serial.

## Start the app

| Platform | Launcher |
| --- | --- |
| Windows | Double-click `Start-StupidPrint.cmd` or run it from the project folder. Use Python 3.10 or later with Tcl/Tk. |
| Linux | Run `bash start.sh` from the project folder. Use Python 3.10 or later with Tcl/Tk and venv support. |

The launchers create a local `.venv`, install the Python dependencies when needed, and start the app. On Debian or Ubuntu, install the OS prerequisites with `sudo apt install python3 python3-tk python3-venv`. On Fedora, use `sudo dnf install python3 python3-tkinter`. For emoji coverage on Linux, install a system emoji font such as Noto Color Emoji.

### Connect the printer

1. Power on the D30 and pair it with your computer. Close any phone app currently using the printer.
2. On Windows, select its **outgoing** Bluetooth serial port. Windows lists it under Bluetooth settings → More Bluetooth settings → COM Ports. On the tested D30N, it was `COM3`.
3. On Linux, pair with BlueZ and expose the printer’s Serial Port Profile using RFCOMM. For example, with the printer’s Bluetooth address and SPP channel, run `sudo rfcomm bind 0 AA:BB:CC:DD:EE:FF 1` and select `/dev/rfcomm0`. Use your actual SPP channel if it differs. Your account needs permission to open that device, commonly through the distribution’s serial-device group. Keep the application running as your regular user.
4. Click **Check status**. The library and last printer port reopen at startup.

The D30N protocol has been tested on Windows. Linux Bluetooth hardware still needs an end-to-end test. This app uses RFCOMM serial for D30-family units with an SPP service.

## Design and save labels

- Use the **Label** inspector for paper size, media type and border. Dimensions are length × width. The D30 renders across the center 12 mm on wider stock.
- Add text, barcodes, images or rules. Drag an element or its purple resize handle, or enter its position and size in millimeters.
- Text supports system fonts, size, bold, italic, underline, horizontal and vertical alignment, wrapping, shrink-to-fit and emoji. Available glyphs vary by installed font and print in monochrome.
- Linear barcode choices are Code 128, Code 39, EAN-13 and UPC-A. The app defaults to at least two printer dots per module for better scan contrast. Use a wider box, shorten the value, or enable **Allow compact bars** on small labels and scan a sample. EAN-13 and UPC-A validate a supplied check digit or calculate it when omitted.
- Edits autosave to the local library. **Save as template** keeps a reusable copy. Open any saved item to edit it, or choose **Use as copy** to start a new project from it.
- **Export project file** creates a portable `.stupidprint` JSON document with its embedded images and imported data. **Export PNG** saves the current label at printer resolution.

The library is stored in `%LOCALAPPDATA%\Stupid Print` on Windows and `$XDG_DATA_HOME/stupid-print` on Linux, with `~/.local/share/stupid-print` as the Linux default. Set `STUPID_PRINT_DATA_DIR` to use a different folder.

## Generate and print a batch

Insert fields into a text or barcode element with the inspector or type them directly:

| Field | Value |
| --- | --- |
| `{{serial}}` | Serial start plus increment per label, with optional zero padding |
| `{{ip}}` | Starting IP plus increment per label |
| `{{subnet}}`, `{{prefix}}`, `{{cidr}}` | Subnet mask, CIDR prefix length, or IP with prefix |
| `{{index}}`, `{{date}}` | One-based label number or current date |
| `{{field:Asset ID}}` | Value in the imported column named `Asset ID` |

1. Open **Batch setup** to set the count, serial start and step, or IP start, mask and step. An IP batch must stay inside its starting subnet. Enter a dotted mask or CIDR prefix for IPv4 and a CIDR prefix for IPv6.
2. For a data merge, choose **Import CSV / Excel**. The first populated row supplies column headers. CSV, TSV, XLSX and XLSM are supported, including worksheet choice. Excel formulas use their saved cached values. A count of **0** uses every imported data row.
3. Browse **Batch preview** to see every label. Use the arrows to change pages or enter a label number to jump to it.
4. Open **Print batch**, then tick individual rows, choose **Select all**, or add ranges such as `1, 4-8, 12`. The dialog previews the focused label and shows the selected count. Set **Copies each** if needed.
5. Click **Print selected**. The app validates the chosen labels before printing and waits for the printer to confirm each one. **Stop after current label** stops the remaining queue. If a job times out, check the physical output before sending it again.

## Development

The GUI uses Tkinter. Pillow handles raster rendering, pySerial handles Bluetooth serial, openpyxl reads Excel files, and python-barcode encodes linear barcodes. Run the tests with `python -m unittest discover -s tests -v` in the project virtual environment.

The D30 wire format is based on published protocol research in [polskafan/phomemo_d30](https://github.com/polskafan/phomemo_d30) and [Phomymo](https://github.com/transcriptionstream/phomymo).
