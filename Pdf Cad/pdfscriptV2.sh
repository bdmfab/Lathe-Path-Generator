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

# Ask the user if they'd like to merge the resulting PDFs into one file
if zenity --question --title="Merge PDFs?" --text="Would you like to merge all $total_files converted PDF(s) into a single PDF using pdfunite?" --width=350; then

    # Check that pdfunite is actually available before going further
    if ! command -v pdfunite &> /dev/null; then
        zenity --error --text="pdfunite was not found on this system.\n\nPlease install poppler-utils (which provides pdfunite) and try again."
        exit 1
    fi

    # Prompt for the desired output filename (without needing the .pdf extension)
    OUTPUT_NAME=$(zenity --entry --title="Merge PDFs" --text="Enter the output filename for the merged PDF:" --entry-text="merged")

    # Exit gracefully if the user cancelled the filename prompt
    if [ -z "$OUTPUT_NAME" ]; then
        zenity --info --text="Merge cancelled."
        exit 0
    fi

    # Strip any .pdf extension the user may have typed, then add it back cleanly
    OUTPUT_NAME="${OUTPUT_NAME%.pdf}"
    OUTPUT_NAME="${OUTPUT_NAME%.PDF}"
    OUTPUT_PATH="PDF/${OUTPUT_NAME}.pdf"

    # Build the list of PDFs to merge, in the same order they were converted
    mapfile -t PDF_FILES < <(printf '%s\n' "$file_list" | sed 's/^- //' | sed 's/\.[^.]*$/.pdf/')

    # Prefix each with the PDF/ directory and confirm each file actually exists
    MERGE_INPUTS=()
    for pdf in "${PDF_FILES[@]}"; do
        candidate="PDF/$pdf"
        if [ -f "$candidate" ]; then
            MERGE_INPUTS+=("$candidate")
        fi
    done

    # Make sure we actually have something to merge
    if [ "${#MERGE_INPUTS[@]}" -eq 0 ]; then
        zenity --error --text="No converted PDF files could be found to merge."
        exit 1
    fi

    # Run pdfunite on the collected files
    if pdfunite "${MERGE_INPUTS[@]}" "$OUTPUT_PATH"; then
        zenity --info --width=400 --title="Merge Complete" --text="Successfully merged ${#MERGE_INPUTS[@]} PDF(s) into:\n\n<b>$TARGET_DIR/$OUTPUT_PATH</b>"
    else
        zenity --error --text="pdfunite failed to merge the PDF files.\n\nCheck that all files are valid, non-encrypted PDFs."
        exit 1
    fi
fi
