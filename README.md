# Stupid Print

Stupid Print is a Python desktop label studio for the Phomemo D30 and Nelko P21. It designs and previews monochrome thermal labels and prints directly over Bluetooth Classic serial.

## Start the app

| Platform | Launcher |
| --- | --- |
| Windows | Double-click `Start-StupidPrint.cmd` or run it from the project folder. |
| Linux | Run `./start.sh` or `sh start.sh` from the project folder. |

Both launchers look for Python 3.10 or later with working Tcl/Tk, create a local virtual environment, and install the Python dependencies. If an existing `.venv` lacks Tcl/Tk, the launcher uses `.venv-tk` for the replacement.

- **Windows.** If no suitable Python is available, the launcher uses Python Install Manager to install a project-local runtime with Tcl/Tk. It can install the manager through WinGet if needed. If your machine blocks WinGet or Microsoft Store access, use the [Python installer](https://www.python.org/downloads/windows/) and include **Tcl/Tk and IDLE**, then run the launcher again.
- **Linux.** If prerequisites are missing, the launcher attempts to install them through APT, DNF or Pacman. The package manager may request your administrator password. For emoji coverage, install a system emoji font such as Noto Color Emoji.

### Connect the printer

1. Power on the printer and pair it with your computer. Close any phone app currently using the printer.
2. On Windows, select its **outgoing** Bluetooth serial port. Windows lists it under Bluetooth settings → More Bluetooth settings → COM Ports. On the tested D30N, it was `COM3`.
3. On Linux, pair with BlueZ and expose the printer’s Serial Port Profile using RFCOMM. For example, with the printer’s Bluetooth address and SPP channel, run `sudo rfcomm bind 0 AA:BB:CC:DD:EE:FF 1` and select `/dev/rfcomm0`. Use your actual SPP channel if it differs. Your account needs permission to open that device, commonly through the distribution’s serial-device group. Keep the application running as your regular user.
4. Click **Find printers** to refresh the list, then select the printer or enter its outgoing serial port. Stupid Print identifies the selected protocol by querying the printer. The library and last port reopen at startup.
5. With a P21 and a readable roll tag, use **Use loaded roll** to apply the printer’s reported label size. The **40 × 14 mm** preset matches Nelko’s included 14 × 40 mm gap labels. If the tag is unreadable, select the size manually. The app checks readable stock again before printing. [Nelko P21 specifications](https://nelko.com/products/nelko-p21-portable-bluetooth-label-printer)

Use **Profiles** to save a named serial port, model and tape width. **Save & use** applies the profile to the current label. A readable P21 roll tag can supply the tape width in the profile editor after a status check. Enter the width manually for D30 and D30N profiles.

The D30N protocol has been tested on Windows. The P21 implementation is based on captured serial traffic and still needs a physical test. Linux Bluetooth hardware also needs an end-to-end test. Both drivers use RFCOMM serial.

## Design and save labels

- Stupid Print starts in dark mode. Use **Light mode** in the header to switch. The app remembers your choice.
- Use **Label** for paper size, media type and border. Dimensions are length × width. Both printers use a 96-dot head at nominal 203 DPI. On wider stock, the editor guides show the centered 12 mm printable strip. [Phomemo D30 specifications](https://phomemo.com/pages/download-center-d30) · [Nelko P21 protocol capture](https://github.com/merlinschumacher/nelko-p21-print)
- Add text, barcodes, images or built-in graphics. **Content** edits values, **Style** controls appearance, and **Place** handles geometry. Use **Hide** beside **Batch preview** when you want more room for the canvas.
- Drag an element or its resize handle. Shift-click on the canvas or use the Layers list to select multiple elements. **Place** offers exact millimeter positions, a 1 mm grid and snap, edge and center alignment, and even spacing for three or more elements. Choose **Printable area** to move the selection as a block or **Selection** to align its members. With the canvas focused, arrow keys nudge by one printer dot and Shift + arrow nudges by 1 mm.
- **Edit** offers undo and redo with Ctrl+Z and Ctrl+Y. Copy and paste selected elements with Ctrl+C and Ctrl+V from the canvas or Layers list, including between projects. The Layers toolbar also has **Duplicate**.
- Double-click text or a barcode on the canvas to edit its value. The editor shows smooth text by default. Turn on **Print dots** to see the exact monochrome raster used by print preview and PNG export.
- Text supports size, bold, italic, underline, alignment, wrapping, shrink-to-fit, quarter-turn rotation and emoji. The searchable font picker puts recommended English fonts above a divider, with other usable system fonts below. Common emoji use built-in monochrome artwork. Other emoji use available system fonts, with a visible placeholder when no glyph is available.
- **+ Graphic** adds inventory and IT symbols, common shapes and rules. **Dither shading** in Style adds tonal detail at print resolution. The catalog is stored as vector commands in `stupid_print/artwork.py`. Projects save a graphic key and its style, so each copy adds only a few fields.
- The graphic picker’s **Safety & science** category includes warning, biohazard, calibration and do-not-remove symbols. **GHS reference** contains monochrome versions of the nine public-domain OSHA pictograms. Regulated chemical labels may require a red frame and additional label elements. [OSHA pictograms and artwork](https://www.osha.gov/hazcom/pictograms)
- Images use contrast adjustment and sharpening before conversion to monochrome. Use **Dither image** for photos or turn it off for solid logos.
- Linear barcode choices are Code 128, Code 39, EAN-13 and UPC-A. UPC-A accepts 11 base digits, a complete 12-digit code, or the same code with the leading zero that some scanners add. Spaces and hyphens in UPC-A and EAN-13 are allowed. A supplied check digit is verified. Keep leading zeroes as text in imported spreadsheets.
- Barcode boxes reserve white space around the bars. The app catches clipped boxes and artwork that covers the scan area before printing. UPC-A and EAN-13 place their digits and extend the guard bars when there is room for a caption. The app defaults to at least two printer dots per module. Give the code enough height and width, then scan a sample on your stock. [GS1 UPC-A specifications](https://ref.gs1.org/standards/genspecs/)
- **+ 2D code** adds QR Code or Data Matrix. Use text, a URL or any batch field as the value. QR offers L, M, Q and H error correction. Data Matrix uses ECC 200. Both reserve a quiet zone on all sides and require at least two printer dots per module. Shorter values fit smaller labels. Scan a sample on your stock before running a batch.
- Open **Built-in templates** in the library to start from one of 12 editable designs. The cable flag and wrap repeat rotated text. The 24- and 48-port patch panels print as 162 mm sections of 12 consecutive ports at 13.5 mm pitch. Check your panel spacing before printing and use **Batch setup → MAC, host & ports** to set the starting port.
- Edits autosave to the local library. **Save as template** keeps a reusable copy. Open any saved item to edit it, or choose **Use as copy** to start a new project from it.
- The **Project files** menu contains template saving and export. Exporting a project creates a portable `.stupidprint` JSON document with embedded images and imported data. PNG export saves the current label at printer resolution. **Export batch PDF** lays out the entire batch as numbered, actual-size labels on US Letter or A4 proof sheets.

The library is stored in `%LOCALAPPDATA%\Stupid Print` on Windows and `$XDG_DATA_HOME/stupid-print` on Linux, with `~/.local/share/stupid-print` as the Linux default. Set `STUPID_PRINT_DATA_DIR` to use a different folder.

## Generate and print a batch

Insert fields into a text or barcode element with the inspector or type them directly:

| Field | Value |
| --- | --- |
| `{{serial}}` | Serial start plus increment per label, with optional zero padding |
| `{{ip}}` | Starting IP plus increment per label |
| `{{subnet}}`, `{{prefix}}`, `{{cidr}}` | Subnet mask, CIDR prefix length, or IP with prefix |
| `{{mac}}` | OUI prefix plus an incrementing hexadecimal suffix, formatted with colons, hyphens or dots |
| `{{hostname}}` | Hostname prefix followed by the configured serial |
| `{{port}}`, `{{port+3}}` | Starting port plus the per-label increment, with an optional offset within each strip |
| `{{index}}` | One-based label number |
| `{{date}}`, `{{date+30d}}`, `{{date-7d}}`, `{{expiry}}` | Today, a day offset, or the expiry offset set in **Batch setup → Dates**, using the chosen date format |
| `{{field:Asset ID}}` | Value in the imported column named `Asset ID` |

1. Open **Batch setup** to set the count, serial start and step, or IP start, mask and step. An IP batch must stay inside its starting subnet. Enter a dotted mask or CIDR prefix for IPv4 and a CIDR prefix for IPv6.
2. For a data merge, choose **Import CSV / Excel**. The first populated row supplies column headers. CSV, TSV, XLSX and XLSM are supported, including worksheet choice. Excel formulas use their saved cached values. A count of **0** uses every imported data row.
3. Browse **Batch preview** to see every label. Use the arrows to change pages or enter a label number to jump to it.
4. Open **Print batch**, then tick individual rows, choose **Select all**, or add ranges such as `1, 4-8, 12`. The dialog previews the focused label and shows the selected count. Set **Copies each** if needed.
5. Click **Print selected**. The app validates the chosen labels before printing. The D30 confirms completed prints. The P21 uses a ready-status check between jobs and reports how many labels were sent. **Stop after current label** stops the remaining queue. If a job times out, check the physical output before sending it again.

**Print history** shows the design, port, timestamp, requested and processed counts, status and job ID. Export the full log as CSV. **Reprint last batch** opens the last attempted print with its saved design, field values, selection and copy count. Review or narrow the selection before sending it again.

**Label stock** saves a manual remaining count and low-stock threshold per printer, label dimensions and media type. Set the estimate when you load a roll. The print dialog warns when the count is low or below the selected job size. The count falls as the D30 confirms labels or the P21 returns ready after sending each label. Adjust the estimate after a jam or timeout based on the physical output. For continuous tape, enter an estimate in labels of the current design size.

## Development

The GUI uses Tkinter. Pillow handles raster rendering, pySerial handles Bluetooth serial, and openpyxl reads Excel files. python-barcode encodes linear barcodes, ZXing-C++ encodes 2D barcodes, and ReportLab writes PDF proofs. Print history and stock estimates are stored in `print-jobs.sqlite3` in the library folder. Run the tests with `python -m unittest discover -s tests -v` in the project virtual environment.

The D30 wire format is based on published protocol research in [polskafan/phomemo_d30](https://github.com/polskafan/phomemo_d30) and [Phomymo](https://github.com/transcriptionstream/phomymo). The P21 driver uses the protocol documented by [merlinschumacher/nelko-p21-print](https://github.com/merlinschumacher/nelko-p21-print).
