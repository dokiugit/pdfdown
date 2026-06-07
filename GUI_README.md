# Scribd Downloader - GUI Version

A user-friendly graphical interface for downloading Scribd documents as PDF files.

## Features

- **Easy-to-use GUI** - Point and click interface with Tkinter
- **Visual progress tracking** - See download status in real-time
- **Live logging** - Watch the process unfold with detailed logs
- **Custom output directory** - Choose where to save your PDFs
- **All original features** - Same powerful Selenium-based downloader backend
- **No login required** - Works without Scribd account
- **Supports both URL formats** - Works with `/document/...` and `/doc/...` links

## Requirements

- Python 3.7 or higher
- Google Chrome browser installed
- Chrome WebDriver (auto-managed by Selenium)

## Installation

1. **Navigate to the repository**
   ```bash
   cd pdfdown
   git checkout gui-version
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements_gui.txt
   ```

## Usage

1. **Run the GUI application**
   ```bash
   python scribd_downloader_gui.py
   ```

2. **Enter the Scribd document URL**
   - Paste your Scribd URL in the text field
   - Supports both `/document/...` and `/doc/...` formats
   - Example: `https://www.scribd.com/document/123456789/Document-Title`

3. **Choose save location**
   - Default is `~/Downloads`
   - Click "Browse" to select a different directory

4. **Click "Download PDF"**
   - Monitor progress in the log window
   - The application will automatically:
     - Open Chrome in background (headless mode)
     - Load and scroll through all pages
     - Remove toolbars and cookie banners
     - Generate the PDF
     - Save it to your chosen location

5. **Done!** - A success message will appear when complete

## Troubleshooting

### ChromeDriver not found
```bash
pip install --upgrade selenium
```

### PDF not saving
- Ensure write permissions in selected directory
- Check Scribd URL is valid and accessible
- For large documents, increase `SCRIBD_CDP_TIMEOUT` environment variable

### Application not responding
- This is normal during PDF generation
- Wait for the success message

## Environment Variables

```bash
# Windows PowerShell
$env:SCRIBD_CDP_TIMEOUT="900"
$env:SCRIBD_SCROLL_DELAY="0.2"
python scribd_downloader_gui.py

# Linux/Mac
export SCRIBD_CDP_TIMEOUT="900"
export SCRIBD_SCROLL_DELAY="0.2"
python scribd_downloader_gui.py
```

Available variables:
- `SCRIBD_CDP_TIMEOUT` - ChromeDriver timeout in seconds (default: 600)
- `SCRIBD_RENDER_SETTLE_TIMEOUT` - Wait time for fonts/images (default: 30)
- `SCRIBD_SCROLL_DELAY` - Delay between page scrolls (default: 0.15)
- `SCRIBD_HEADLESS` - Set to "0" for visible browser (default: 1)

## License

MIT License - See LICENSE file for details

## Disclaimer

This tool is for educational purposes. Respect copyright laws and Scribd's Terms of Service. Only download documents you have rights to access.
