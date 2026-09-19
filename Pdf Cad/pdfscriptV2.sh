#!/usr/bin/env bash

# Open a Zenity folder selection dialog
TARGET_DIR=$(zenity --file-selection --directory --title="Select Drawing Directory")

# Exit if the user cancels or closes the dialog
if [ -z "$TARGET_DIR" ]; then
    echo "Operation canceled by user."
    exit 0
fi

# Navigate to the chosen directory
cd "$TARGET_DIR" || exit 1

# Define the path to your specific QCAD installation binary
QCAD_BIN="/opt/qcad-3.32.2-pro-linux-qt5.14-x86_64/dwg2pdf"

# Verify if the QCAD executable exists at that path
if [ ! -f "$QCAD_BIN" ]; then
    zenity --error --text="QCAD executable not found at:\n$QCAD_BIN\n\nPlease check the path in the script."
    exit 1
fi

# Count the total number of target drawing files
total_files=0
for f in *.{dxf,dwg,DXF,DWG}; do
    [ -e "$f" ] && ((total_files++))
done

# If no files are found, alert the user and exit
if [ "$total_files" -eq 0 ]; then
    zenity --warning --text="No DXF or DWG files found in this directory."
    exit 0
fi

# Create a temporary file to hold the list of processed files safely
TEMP_LIST=$(mktemp)

# Create the PDF directory safely
mkdir -p PDF

# Start the conversion loop
current_file=0
for f in *.{dxf,dwg,DXF,DWG}; do
    [ -e "$f" ] || continue
    ((current_file++))
    
    # Save the file name to our temporary file (persists across subshells)
    echo "- $f" >> "$TEMP_LIST"
    
    # Calculate current percentage
    percentage=$(( current_file * 100 / (total_files + 1)))
    
    # Update the Zenity progress bar text
    echo "# Converting: $f ($current_file/$total_files)"
    echo "$percentage"
    
    # Run the QCAD conversion utility
    "$QCAD_BIN" -a -margin=5 -l -c -p Tabloid -f -o "PDF/${f%.*}.pdf" "$f"
    
done | zenity --progress --title="QCAD PDF Export" --text="Starting batch export..." --percentage=0 --auto-close

# Check if Zenity was closed early (cancelled by user)
if [ "${PIPESTATUS}" -ne 0 ]; then
    rm -f "$TEMP_LIST"
    zenity --info --text="Export cancelled by user."
    exit 0
fi

# Read the contents of the temporary file into a final variable
file_list=$(cat "$TEMP_LIST")

# Delete the temporary file to keep your system clean
rm -f "$TEMP_LIST"

# Show the detailed success notification with the full list populated perfectly
zenity --info --width=450 --height=350 --title="Export Complete" --text="Successfully converted <b>$total_files</b> drawing(s)!\n\n<b>Saved in:</b>\n$TARGET_DIR/PDF\n\n<b>Processed Files:</b>\n$file_list"

