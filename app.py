"""
Scribd Document Downloader — Streamlit GUI
==========================================
Paste a Scribd URL, click Download, and get a PDF.

Run with:
    streamlit run scribd_downloader_streamlit.py

Requirements:
    pip install streamlit selenium
    Google Chrome must be installed on the machine.
"""

import base64
import os
import re
import shutil
import tempfile
import time
from urllib.parse import unquote, urlparse

import streamlit as st

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Scribd Downloader",
    page_icon="📄",
    layout="centered",
)

# ── Constants / env tunables ─────────────────────────────────────────────────
DEFAULT_CDP_TIMEOUT = int(os.getenv("SCRIBD_CDP_TIMEOUT", "600"))
DEFAULT_RENDER_SETTLE = int(os.getenv("SCRIBD_RENDER_SETTLE_TIMEOUT", "30"))
DEFAULT_SCROLL_DELAY = float(os.getenv("SCRIBD_SCROLL_DELAY", "0.15"))
PDF_CHUNK = int(os.getenv("SCRIBD_PDF_STREAM_CHUNK_SIZE", str(1024 * 1024)))
DEFAULT_W = 7.25
DEFAULT_H = 10.5

# ── Core downloader logic (adapted from scribd-downloader.py) ────────────────

def convert_scribd_link(url: str) -> str | None:
    match = re.search(r"https://www\.scribd\.com/(?:document|doc)/(\d+)/", url)
    if not match:
        return None
    return f"https://www.scribd.com/embeds/{match.group(1)}/content"


def get_filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    last = path.split("/")[-1] if path else "scribd_document"
    return f"{unquote(last)}.pdf"


def build_chrome_options(headless: bool, profile_dir: str):
    from selenium.webdriver.chrome.options import Options
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1600,2200")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--remote-debugging-port=0")
    opts.add_argument(f"--user-data-dir={profile_dir}")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--force-color-profile=srgb")
    opts.add_argument("--hide-scrollbars")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    return opts


def hide_cookie_dialogs(driver):
    driver.execute_script("""
        const selectors=[
            '[class*="cookie"]','[class*="Cookie"]','[class*="consent"]',
            '[class*="Consent"]','[class*="gdpr"]','[class*="GDPR"]',
            '[id*="cookie"]','[id*="consent"]','[class*="privacy-notice"]',
            '.cc-window','.cc-banner','#onetrust-consent-sdk',
            '[class*="osano-cm"]','[id*="osano"]'
        ];
        selectors.forEach(s=>{
            try{document.querySelectorAll(s).forEach(e=>e.remove())}catch(e){}
        });
    """)


def scroll_through_pages(driver, delay: float, log):
    scrolled = 0
    stable = 0
    last_total = -1
    while stable < 2:
        pages = driver.find_elements("css selector", "[class*='page']")
        total = len(pages)
        if total == 0:
            log("⚠️ No page elements detected.")
            return 0
        if total == last_total:
            stable += 1
        else:
            stable = 0
            last_total = total
        if scrolled == 0:
            log(f"📄 Found {total} pages, scrolling…")
        elif total > scrolled:
            log(f"📄 Detected {total} pages after lazy loading, continuing…")
        for i in range(scrolled, total):
            driver.execute_script(
                "arguments[0].scrollIntoView({behavior:'instant',block:'center'});",
                pages[i],
            )
            time.sleep(delay)
            if (i + 1) % 20 == 0:
                log(f"   ↳ Scrolled {i+1}/{total} pages…")
        scrolled = total
        time.sleep(0.5)
    log(f"✅ All {scrolled} pages loaded.")
    return scrolled


def prepare_document_for_print(driver, log):
    r = driver.execute_script("""
        const res={top:false,bot:false,cnt:0};
        const t=document.querySelector('.toolbar_top');
        if(t){t.remove();res.top=true;}
        const b=document.querySelector('.toolbar_bottom');
        if(b){b.remove();res.bot=true;}
        document.querySelectorAll('.document_scroller').forEach(e=>{
            e.setAttribute('data-scribd-print-root','true');
            e.style.cssText='position:static;top:auto;bottom:auto;left:auto;right:auto;overflow:visible;max-height:none;height:auto;margin:0;padding:0;';
            res.cnt+=1;
        });
        return res;
    """)
    if r.get("top"):
        log("🗑️  Top toolbar removed.")
    if r.get("bot"):
        log("🗑️  Bottom toolbar removed.")
    log(f"🔧 Adjusted {r.get('cnt',0)} scroll containers for print.")


def inject_print_styles(driver, log):
    driver.execute_script("""
        const ex=document.getElementById('scribd-print-styles');
        if(ex)ex.remove();
        const s=document.createElement('style');
        s.id='scribd-print-styles';
        s.textContent=`
            [class*="cookie"],[class*="Cookie"],[class*="consent"],[class*="Consent"],
            [class*="gdpr"],[class*="privacy-notice"],[class*="notice-banner"],
            [id*="cookie"],[id*="consent"],[class*="osano-cm"],[id*="osano"]{
                display:none!important;visibility:hidden!important;
                opacity:0!important;height:0!important;overflow:hidden!important;
            }
            [data-scribd-print-root="true"],.document_scroller{
                position:static!important;top:auto!important;right:auto!important;
                bottom:auto!important;left:auto!important;overflow:visible!important;
                height:auto!important;max-height:none!important;margin:0!important;padding:0!important;
            }
            @media print{
                @page{size:7.25in 10.5in;margin:0;}
                html,body{margin:0!important;padding:0!important;
                    -webkit-print-color-adjust:exact!important;print-color-adjust:exact!important;}
                .toolbar_top,.toolbar_bottom{display:none!important;}
                .outer_page{margin:0!important;break-inside:avoid!important;break-after:page!important;}
                .outer_page:last-of-type{break-after:auto!important;}
                mjx-container,.MathJax,.katex,math,svg{visibility:visible!important;overflow:visible!important;}
            }
        `;
        document.head.appendChild(s);
    """)
    log("🎨 Print CSS injected.")


def wait_for_render_stability(driver, timeout_s: int, log):
    driver.set_script_timeout(timeout_s + 5)
    try:
        result = driver.execute_async_script("""
            const budget=arguments[0], done=arguments[arguments.length-1];
            const start=performance.now();
            let ticks=0, last='';
            function snap(){
                const pages=Array.from(document.querySelectorAll("[class*='page']"));
                const h=pages.slice(0,12).map(e=>Math.round(e.getBoundingClientRect().height));
                const pend=Array.from(document.images||[]).filter(i=>!i.complete).length;
                const busy=document.querySelectorAll("[aria-busy='true'],[class*='loading'],[class*='spinner']").length;
                return JSON.stringify({c:pages.length,h,pend,busy});
            }
            function tick(){
                const s=snap();
                const p=JSON.parse(s);
                if(!p.pend&&!p.busy&&s===last){ticks++;}else{ticks=0;}
                last=s;
                if(ticks>=2){done({timedOut:false});return;}
                if(performance.now()-start>=budget){done({timedOut:true});return;}
                requestAnimationFrame(()=>setTimeout(tick,200));
            }
            (document.fonts&&document.fonts.ready?document.fonts.ready.catch(()=>{}):Promise.resolve())
                .finally(()=>requestAnimationFrame(()=>setTimeout(tick,200)));
        """, int(timeout_s * 1000))
        if result.get("timedOut"):
            log("⏱️  Render settle timed out; continuing with best effort.")
        else:
            log("✅ Document render settled.")
    except Exception as e:
        log(f"⚠️  Render settle check failed: {e}")


def detect_paper_size(driver):
    r = driver.execute_script("""
        for(const sel of ['.outer_page','.newpage','.outer_page_container',"[class*='page']"]){
            const el=document.querySelector(sel);
            if(!el)continue;
            const rc=el.getBoundingClientRect();
            if(rc.width>0&&rc.height>0)return{w:rc.width/96,h:rc.height/96,sel};
        }
        return null;
    """)
    if not r:
        return DEFAULT_W, DEFAULT_H
    return max(1.0, round(r["w"], 3)), max(1.0, round(r["h"], 3))


def read_stream_to_bytes(driver, handle: str) -> bytes:
    buf = b""
    while True:
        chunk = driver.execute_cdp_cmd("IO.read", {"handle": handle, "size": PDF_CHUNK})
        data = chunk.get("data", "")
        if not data and chunk.get("eof"):
            break
        if chunk.get("base64Encoded"):
            buf += base64.b64decode(data)
        else:
            buf += data.encode("utf-8")
        if chunk.get("eof"):
            break
    driver.execute_cdp_cmd("IO.close", {"handle": handle})
    return buf


def export_pdf_bytes(driver, pw: float, ph: float, timeout_s: int, log) -> bytes:
    # Extend Selenium's internal HTTP timeout so huge docs don't time out
    executor = getattr(driver, "command_executor", None)
    if executor:
        cfg = getattr(executor, "client_config", None) or getattr(executor, "_client_config", None)
        if cfg:
            cfg.timeout = timeout_s

    opts = dict(
        landscape=False, displayHeaderFooter=False, printBackground=True,
        scale=1, paperWidth=pw, paperHeight=ph,
        marginTop=0, marginBottom=0, marginLeft=0, marginRight=0,
        preferCSSPageSize=False,
    )
    try:
        result = driver.execute_cdp_cmd("Page.printToPDF", {**opts, "transferMode": "ReturnAsStream"})
        if result.get("stream"):
            return read_stream_to_bytes(driver, result["stream"])
        return base64.b64decode(result["data"])
    except Exception as e:
        log(f"⚠️  Stream mode failed ({e}), retrying without stream…")
        result = driver.execute_cdp_cmd("Page.printToPDF", opts)
        return base64.b64decode(result["data"])


def run_download(url: str, scroll_delay: float, cdp_timeout: int,
                 render_timeout: int, headless: bool, log) -> bytes | None:
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException

    embed_url = convert_scribd_link(url)
    if not embed_url:
        log("❌ Invalid Scribd URL. Use: https://www.scribd.com/document/ID/Title")
        return None

    log(f"🔗 Embed URL: {embed_url}")

    profile_dir = tempfile.mkdtemp(prefix="scribd-chrome-")
    driver = None
    try:
        log("🚀 Starting Chrome…")
        opts = build_chrome_options(headless, profile_dir)
        driver = webdriver.Chrome(options=opts)

        driver.get(embed_url)
        time.sleep(1)
        hide_cookie_dialogs(driver)
        log("🍪 Cookie dialogs hidden.")

        pages = scroll_through_pages(driver, scroll_delay, log)
        if pages == 0:
            log("❌ No pages detected — check the URL or try a different document.")
            return None

        prepare_document_for_print(driver, log)
        inject_print_styles(driver, log)
        wait_for_render_stability(driver, render_timeout, log)

        driver.execute_cdp_cmd("Emulation.setEmulatedMedia", {"media": "print"})
        pw, ph = detect_paper_size(driver)
        log(f"📐 Page size: {pw:.2f}\" × {ph:.2f}\"")
        driver.execute_script("window.scrollTo(0,0);")

        log("💾 Exporting PDF…")
        pdf_bytes = export_pdf_bytes(driver, pw, ph, cdp_timeout, log)
        log(f"✅ Done! PDF size: {len(pdf_bytes)/1024:.1f} KB")
        return pdf_bytes

    except (WebDriverException, RuntimeError) as e:
        log(f"❌ Error: {e}")
        return None
    finally:
        if driver:
            driver.quit()
            log("🔒 Browser closed.")
        shutil.rmtree(profile_dir, ignore_errors=True)


# ── Streamlit UI ─────────────────────────────────────────────────────────────

st.title("📄 Scribd Downloader")
st.caption("Download Scribd documents as PDF — no login required.")

st.divider()

url_input = st.text_input(
    "Scribd Document URL",
    placeholder="https://www.scribd.com/document/123456789/Document-Title",
)

with st.expander("⚙️ Advanced settings"):
    col1, col2 = st.columns(2)
    with col1:
        scroll_delay = st.slider("Scroll delay (s)", 0.05, 1.0, DEFAULT_SCROLL_DELAY, 0.05,
                                  help="Pause between page scrolls. Increase for slow connections.")
        cdp_timeout = st.number_input("CDP timeout (s)", 60, 1800, DEFAULT_CDP_TIMEOUT, 60,
                                       help="Max time Chrome can spend generating the PDF.")
    with col2:
        render_timeout = st.number_input("Render settle timeout (s)", 5, 120, DEFAULT_RENDER_SETTLE, 5,
                                          help="Max time to wait for fonts/images to finish loading.")
        headless = st.checkbox("Headless mode", value=True,
                                help="Uncheck to see the Chrome window (useful for debugging).")

st.divider()

if st.button("⬇️ Download PDF", type="primary", disabled=not url_input.strip()):
    log_box = st.empty()
    logs: list[str] = []

    def log(msg: str):
        logs.append(msg)
        log_box.markdown("\n\n".join(logs))

    filename = get_filename_from_url(url_input.strip())
    log(f"📋 Output filename: **{filename}**")

    with st.spinner("Working… this may take a minute for large documents."):
        pdf_bytes = run_download(
            url_input.strip(),
            scroll_delay=scroll_delay,
            cdp_timeout=cdp_timeout,
            render_timeout=render_timeout,
            headless=headless,
            log=log,
        )

    if pdf_bytes:
        st.success("PDF is ready!")
        st.download_button(
            label="📥 Save PDF",
            data=pdf_bytes,
            file_name=filename,
            mime="application/pdf",
            type="primary",
        )
    else:
        st.error("Download failed. Check the log above for details.")

st.divider()
st.caption(
    "Based on [scribd-downloader](https://github.com/themrsami/scribd-downloader) by themrsami · "
    "For educational use only. Respect copyright laws and Scribd's ToS."
)
