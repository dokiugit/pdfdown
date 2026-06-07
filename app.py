"""
Scribd Document Downloader - GUI Version
=========================================

A Tkinter-based GUI wrapper around the Selenium-based Scribd downloader.
Provides a user-friendly interface for downloading Scribd documents as PDF.
"""

import base64
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from tkinter import (
    Tk, Label, Entry, Button, Text, Frame, StringVar, filedialog, messagebox, ttk
)
from urllib.parse import unquote, urlparse

from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options


DEFAULT_CDP_TIMEOUT_SECONDS = int(os.getenv("SCRIBD_CDP_TIMEOUT", "600"))
DEFAULT_RENDER_SETTLE_TIMEOUT_SECONDS = int(
    os.getenv("SCRIBD_RENDER_SETTLE_TIMEOUT", "30")
)
DEFAULT_SCROLL_DELAY_SECONDS = float(os.getenv("SCRIBD_SCROLL_DELAY", "0.15"))
PDF_STREAM_CHUNK_SIZE = int(os.getenv("SCRIBD_PDF_STREAM_CHUNK_SIZE", str(1024 * 1024)))
HEADLESS_ENABLED = os.getenv("SCRIBD_HEADLESS", "1").strip().lower() not in {
    "0", "false", "no",
}
DEFAULT_PAPER_WIDTH_INCHES = 7.25
DEFAULT_PAPER_HEIGHT_INCHES = 10.5


def build_chrome_options(runtime_profile_dir):
    """Create Chrome options for reliable headless PDF generation."""
    options = Options()
    if HEADLESS_ENABLED:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1600,2200")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--remote-debugging-port=0")
    options.add_argument(f"--user-data-dir={runtime_profile_dir}")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--force-color-profile=srgb")
    options.add_argument("--hide-scrollbars")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    return options


def convert_scribd_link(url):
    """Convert a Scribd document URL to the embed/content URL."""
    match = re.search(r"https://www\.scribd\.com/(?:document|doc)/(\d+)/", url)
    if not match:
        return "Invalid Scribd URL"
    return f"https://www.scribd.com/embeds/{match.group(1)}/content"


def get_filename_from_url(url):
    """Build an output filename from the last URL path segment."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    last_segment = path.split("/")[-1] if path else "scribd_document"
    return f"{unquote(last_segment)}.pdf"


def configure_command_timeout(driver, timeout_seconds):
    """Increase the Selenium HTTP timeout."""
    executor = getattr(driver, "command_executor", None)
    if executor is None:
        return
    client_config = getattr(executor, "client_config", None)
    if client_config is None:
        client_config = getattr(executor, "_client_config", None)
    if client_config is not None:
        client_config.timeout = timeout_seconds


def hide_cookie_dialogs(driver):
    """Dismiss and remove common cookie banners."""
    driver.execute_script(
        "document.querySelectorAll('[class*=\"cookie\"], [class*=\"consent\"], [class*=\"gdpr\"]').forEach(e => e.remove());"
    )


def scroll_through_pages(driver, scroll_delay_seconds, callback=None):
    """Scroll through all detected pages."""
    scrolled_count = 0
    stable_rounds = 0
    last_total_pages = -1
    while stable_rounds < 2:
        page_elements = driver.find_elements("css selector", "[class*='page']")
        total_pages = len(page_elements)
        if total_pages == 0:
            return 0
        if total_pages == last_total_pages:
            stable_rounds += 1
        else:
            stable_rounds = 0
            last_total_pages = total_pages
        for index in range(scrolled_count, total_pages):
            driver.execute_script(
                "arguments[0].scrollIntoView({behavior: 'instant', block: 'center'});",
                page_elements[index],
            )
            time.sleep(scroll_delay_seconds)
            if (index + 1) % 10 == 0 and callback:
                callback(f"Scrolled {index + 1}/{total_pages} pages...")
        scrolled_count = total_pages
        time.sleep(0.5)
    return scrolled_count


def prepare_document_for_print(driver):
    """Remove UI chrome and make scrollers printable."""
    driver.execute_script(
        "document.querySelector('.toolbar_top')?.remove(); document.querySelector('.toolbar_bottom')?.remove();"
    )


def inject_print_styles(driver):
    """Install print CSS."""
    driver.execute_script(
        "const s = document.createElement('style'); s.textContent = '@media print { .toolbar_top, .toolbar_bottom { display: none; } }'; document.head.appendChild(s);"
    )


def wait_for_render_stability(driver, timeout_seconds):
    """Wait for render stability."""
    try:
        driver.set_script_timeout(timeout_seconds + 5)
        driver.execute_async_script("setTimeout(arguments[0], 500);")
    except:
        pass


def detect_document_paper_size(driver):
    """Detect paper size from rendered page."""
    try:
        paper_size = driver.execute_script(
            "const e = document.querySelector('.outer_page') || document.querySelector('[class*=\"page\"]'); const r = e?.getBoundingClientRect(); return r ? {w: r.width/96, h: r.height/96} : null;"
        )
        if paper_size:
            return {
                "widthInches": max(1.0, round(paper_size["w"], 3)),
                "heightInches": max(1.0, round(paper_size["h"], 3)),
            }
    except:
        pass
    return {
        "widthInches": DEFAULT_PAPER_WIDTH_INCHES,
        "heightInches": DEFAULT_PAPER_HEIGHT_INCHES,
    }


def read_pdf_stream_to_file(driver, stream_handle, filename):
    """Read PDF stream to file."""
    try:
        with open(filename, "wb") as f:
            while True:
                chunk = driver.execute_cdp_cmd("IO.read", {"handle": stream_handle, "size": PDF_STREAM_CHUNK_SIZE})
                data = chunk.get("data", "")
                if not data and chunk.get("eof"):
                    break
                if chunk.get("base64Encoded"):
                    f.write(base64.b64decode(data))
                else:
                    f.write(data.encode("utf-8"))
                if chunk.get("eof"):
                    break
    finally:
        driver.execute_cdp_cmd("IO.close", {"handle": stream_handle})


def save_pdf_directly(driver, filename, timeout_seconds=DEFAULT_CDP_TIMEOUT_SECONDS, paper_size=None):
    """Generate and save PDF."""
    configure_command_timeout(driver, timeout_seconds)
    if paper_size is None:
        paper_size = {
            "widthInches": DEFAULT_PAPER_WIDTH_INCHES,
            "heightInches": DEFAULT_PAPER_HEIGHT_INCHES,
        }
    pdf_options = {
        "landscape": False,
        "displayHeaderFooter": False,
        "printBackground": True,
        "scale": 1,
        "paperWidth": paper_size["widthInches"],
        "paperHeight": paper_size["heightInches"],
        "marginTop": 0,
        "marginBottom": 0,
        "marginLeft": 0,
        "marginRight": 0,
        "preferCSSPageSize": False,
    }
    try:
        try:
            result = driver.execute_cdp_cmd("Page.printToPDF", {**pdf_options, "transferMode": "ReturnAsStream"})
            if result.get("stream"):
                read_pdf_stream_to_file(driver, result["stream"], filename)
            else:
                with open(filename, "wb") as f:
                    f.write(base64.b64decode(result["data"]))
        except:
            result = driver.execute_cdp_cmd("Page.printToPDF", pdf_options)
            with open(filename, "wb") as f:
                f.write(base64.b64decode(result["data"]))
        return os.path.abspath(filename)
    except Exception as error:
        raise Exception(f"Error saving PDF: {error}")


class ScribdDownloaderGUI:
    """GUI for Scribd downloader."""

    def __init__(self, root):
        self.root = root
        self.root.title("Scribd PDF Downloader")
        self.root.geometry("700x600")
        self.download_thread = None
        self.is_downloading = False
        self.setup_ui()

    def setup_ui(self):
        """Setup GUI components."""
        Label(self.root, text="Scribd PDF Downloader", font=("Arial", 18, "bold")).pack(pady=10)

        url_frame = Frame(self.root)
        url_frame.pack(pady=10, padx=10, fill="x")
        Label(url_frame, text="Scribd URL:", font=("Arial", 10)).pack(anchor="w")
        self.url_entry = Entry(url_frame, font=("Arial", 10), width=70)
        self.url_entry.pack(pady=5, fill="x")
        self.url_entry.insert(0, "https://www.scribd.com/document/...")

        dir_frame = Frame(self.root)
        dir_frame.pack(pady=10, padx=10, fill="x")
        Label(dir_frame, text="Save Location:", font=("Arial", 10)).pack(anchor="w")
        dir_input_frame = Frame(dir_frame)
        dir_input_frame.pack(fill="x", pady=5)
        self.dir_entry = Entry(dir_input_frame, font=("Arial", 10))
        self.dir_entry.pack(side="left", fill="x", expand=True)
        self.dir_entry.insert(0, str(Path.home() / "Downloads"))
        Button(dir_input_frame, text="Browse", command=self.browse_directory, width=10).pack(side="left", padx=5)

        self.download_btn = Button(self.root, text="Download PDF", command=self.start_download, 
                                   font=("Arial", 12, "bold"), bg="#4CAF50", fg="white", padx=20, pady=10)
        self.download_btn.pack(pady=15)

        self.progress_bar = ttk.Progressbar(self.root, mode="indeterminate", length=400)
        self.progress_bar.pack(pady=10)

        Label(self.root, text="Log:", font=("Arial", 10, "bold")).pack(anchor="w", padx=10)
        self.log_text = Text(self.root, font=("Courier", 9), height=15, width=80, state="disabled")
        self.log_text.pack(padx=10, pady=5, fill="both", expand=True)

    def browse_directory(self):
        """Browse for directory."""
        directory = filedialog.askdirectory(title="Select Download Location")
        if directory:
            self.dir_entry.delete(0, "end")
            self.dir_entry.insert(0, directory)

    def log_message(self, message):
        """Log message."""
        self.log_text.config(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")
        self.root.update()

    def start_download(self):
        """Start download thread."""
        if self.is_downloading:
            messagebox.showwarning("Warning", "Download in progress!")
            return
        url = self.url_entry.get().strip()
        if not url or url == "https://www.scribd.com/document/...":
            messagebox.showerror("Error", "Enter a valid Scribd URL")
            return
        self.is_downloading = True
        self.download_btn.config(state="disabled")
        self.progress_bar.start()
        self.download_thread = threading.Thread(target=self.download_pdf, args=(url,), daemon=True)
        self.download_thread.start()

    def download_pdf(self, url):
        """Download PDF."""
        try:
            self.log_message("=" * 60)
            self.log_message("Starting Scribd PDF Download")
            self.log_message("=" * 60)

            converted_url = convert_scribd_link(url)
            if converted_url == "Invalid Scribd URL":
                raise ValueError("Invalid Scribd URL")

            pdf_filename = get_filename_from_url(url)
            output_dir = self.dir_entry.get()
            pdf_path = os.path.join(output_dir, pdf_filename)

            self.log_message(f"Output: {pdf_filename}")

            with tempfile.TemporaryDirectory(prefix="scribd-") as runtime_profile_dir:
                driver = None
                try:
                    self.log_message("[1/7] Starting Chrome...")
                    driver = webdriver.Chrome(options=build_chrome_options(runtime_profile_dir))
                    driver.get(converted_url)
                    time.sleep(1)

                    self.log_message("[2/7] Hiding dialogs...")
                    hide_cookie_dialogs(driver)

                    self.log_message("[3/7] Scrolling pages...")
                    total_pages = scroll_through_pages(driver, DEFAULT_SCROLL_DELAY_SECONDS, callback=self.log_message)
                    if total_pages == 0:
                        raise RuntimeError("No pages detected")

                    self.log_message(f"[4/7] Preparing document ({total_pages} pages)...")
                    prepare_document_for_print(driver)
                    inject_print_styles(driver)

                    self.log_message("[5/7] Waiting for stability...")
                    wait_for_render_stability(driver, DEFAULT_RENDER_SETTLE_TIMEOUT_SECONDS)
                    driver.execute_cdp_cmd("Emulation.setEmulatedMedia", {"media": "print"})

                    self.log_message("[6/7] Detecting page size...")
                    paper_size = detect_document_paper_size(driver)
                    driver.execute_script("window.scrollTo(0, 0);")

                    self.log_message("[7/7] Generating PDF...")
                    saved_path = save_pdf_directly(driver, pdf_path, paper_size=paper_size)

                    self.log_message("\n✓ SUCCESS!")
                    self.log_message(f"Saved to: {saved_path}")
                    messagebox.showinfo("Success", f"PDF downloaded!\n\n{saved_path}")

                except (RuntimeError, ValueError) as error:
                    self.log_message(f"\n✗ ERROR: {error}")
                    messagebox.showerror("Failed", str(error))
                finally:
                    if driver:
                        driver.quit()

        except Exception as error:
            self.log_message(f"\n✗ ERROR: {error}")
            messagebox.showerror("Error", str(error))
        finally:
            self.is_downloading = False
            self.download_btn.config(state="normal")
            self.progress_bar.stop()


def main():
    """Run GUI."""
    root = Tk()
    ScribdDownloaderGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
