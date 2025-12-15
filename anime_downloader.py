import time
import os
import requests
import threading
import queue
from tqdm import tqdm
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import sys

class Colors:
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    MAGENTA = '\033[95m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

download_queue = queue.Queue()

class AnimeDownloader:
    def __init__(self, download_dir="downloads"):
        self.download_dir = os.path.abspath(download_dir)
        if not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir)

        chrome_options = Options()
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        
        prefs = {
            "download.default_directory": self.download_dir,
            "download.prompt_for_download": False,
        }
        chrome_options.add_experimental_option("prefs", prefs)
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument('--log-level=3')
        chrome_options.add_argument('--silent')

        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    def start_download_worker(self):
        """Starts the background worker thread."""
        worker = threading.Thread(target=self._download_worker, daemon=True)
        worker.start()
        return worker

    def _download_worker(self):
        """Consumer: Pulls tasks from queue and downloads them."""
        while True:
            task = download_queue.get()
            if task is None:
                break
            
            if len(task) == 5:
                episode_num, url, cookies, user_agent, form_data = task
            else:
                episode_num, url, cookies, user_agent = task
                form_data = None
                
            self._download_file(episode_num, url, cookies, user_agent, form_data)
            download_queue.task_done()

    def _download_file(self, episode_num, url, cookies, user_agent, form_data=None):
        """Downloads the file using requests with progress bar."""
        filename = os.path.join(self.download_dir, f"Episode_{episode_num}.mp4")
        headers = {
            "User-Agent": user_agent, 
            "Referer": "https://kwik.mewcdn.online/",
            "Origin": "https://kwik.mewcdn.online"
        }
        
        print(f"\n[Ep {episode_num}] Starting download...")
        
        try:
            if form_data:
                print(f"[Ep {episode_num}] Sending POST request to {url}")
                s = requests.Session()
                s.headers.update(headers)
                s.cookies.update(cookies)
                
                r = s.post(url, data=form_data, stream=True, allow_redirects=True)
            else:
                print(f"[Ep {episode_num}] Sending GET request to {url}")
                r = requests.get(url, stream=True, cookies=cookies, headers=headers, allow_redirects=True)

            r.raise_for_status()
            
            content_type = r.headers.get('content-type', '').lower()
            if 'text/html' in content_type:
                print(f"[Ep {episode_num}] Warning: Received HTML instead of video. Possible broken link or CAPTCHA.")
                with open(f"error_ep{episode_num}.html", "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
                print(f"[Ep {episode_num}] Saved response to error_ep{episode_num}.html")
                return

            total_size = int(r.headers.get('content-length', 0))
            
            with open(filename, 'wb') as f, tqdm(
                desc=f"Ep {episode_num}",
                total=total_size,
                unit='iB',
                unit_scale=True,
                unit_divisor=1024,
            ) as bar:
                for chunk in r.iter_content(chunk_size=8192):
                    size = f.write(chunk)
                    bar.update(size)
            
            print(f"[Ep {episode_num}] Download Complete!")
            
        except Exception as e:
            print(f"[Ep {episode_num}] Download Failed: {e}")



    def monitor_download(self, episode_num):
        """Monitors the download directory for the new file and renames it."""
        
        stop_animation = threading.Event()
        animation_thread = threading.Thread(
            target=self._show_download_progress,
            args=(stop_animation, f"  -> Downloading Ep {episode_num}", "")
        )
        animation_thread.daemon = True
        animation_thread.start()
        time.sleep(0.2)
        
        initial_files = set(os.listdir(self.download_dir))
        
        new_file = None
        start_time = time.time()
        while time.time() - start_time < 60:
            current_files = set(os.listdir(self.download_dir))
            diff = current_files - initial_files
            if diff:
                for f in diff:
                    if not f.startswith("."):
                        new_file = f
                        break
                if new_file:
                    break
            time.sleep(0.5)
            
        if not new_file:
            stop_animation.set()
            animation_thread.join()
            print(f"\r{Colors.RED}  -> Error: Download did not start within timeout.{Colors.END}")
            return False

        while new_file.endswith(".crdownload") or new_file.endswith(".part"):
            time.sleep(0.5)
            if not os.path.exists(os.path.join(self.download_dir, new_file)):
                current_files = set(os.listdir(self.download_dir))
                diff = current_files - initial_files
                final_file = None
                for f in diff:
                    if not f.endswith(".crdownload") and not f.endswith(".part"):
                        final_file = f
                        break
                if final_file:
                    new_file = final_file
                    break
        
        elapsed = time.time() - start_time
        if elapsed < 1.5:
            time.sleep(1.5 - elapsed)
        
        stop_animation.set()
        animation_thread.join()
        
        print(f"\r{Colors.GREEN}  -> Download complete: {new_file}{Colors.END}")
        
        final_name = f"Episode_{episode_num}.mp4"
        final_path = os.path.join(self.download_dir, final_name)
        original_path = os.path.join(self.download_dir, new_file)
        
        if os.path.exists(final_path):
            os.remove(final_path)
            
        try:
            os.rename(original_path, final_path)
            print(f"{Colors.GREEN}  -> Renamed to: {final_name}{Colors.END}")
            return True
        except Exception as e:
            print(f"{Colors.RED}  -> Error renaming file: {e}{Colors.END}")
            return False
    
    def _show_download_progress(self, stop_event, message, filename=""):
        """Show animated download progress."""
        spinner = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        blocks = ["█", "▓", "▒", "░"]
        i = 0
        while not stop_event.is_set():
            block_pattern = "".join([blocks[(i + j) % len(blocks)] for j in range(4)])
            sys.stdout.write(f"\r{Colors.YELLOW}{message} {spinner[i % len(spinner)]} {Colors.CYAN}{block_pattern}{Colors.END}")
            sys.stdout.flush()
            time.sleep(0.15)
            i += 1
        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()


    def scrape_and_queue(self, start_ep, base_url, target_quality=None, target_type=None):
        """
        Sequential scraping and downloading. Loops until 404 or error.
        """
        downloaded_episodes = []
        
        current_ep = start_ep
        consecutive_errors = 0
        
        print(f"Connecting to {base_url}{start_ep}/ to fetch episode list...")
        try:
            self.driver.get(f"{base_url}{start_ep}/")
            time.sleep(3)
            
            eps = self.driver.find_elements(By.CSS_SELECTOR, "a.ep-item")
            if eps:
                total_eps = len(eps)
                last_ep = eps[-1].get_attribute("data-number")
                print(f"Total Episodes Found: {Colors.RED} {total_eps} {Colors.END} (Last Episode: {last_ep})")
            else:
                print("Could not determine total episodes (list not found).")
        except Exception as e:
            print(f"Error fetching episode list: {e}")

        print(f"{Colors.MAGENTA}{Colors.BOLD}Starting Download...{Colors.END}\n")
        
        while True:
            print(f"\n{Colors.BLUE}{Colors.BOLD}Scraping Episode {current_ep}: {Colors.CYAN}{base_url}{current_ep}/{Colors.END}")
            
            try:
                if self.driver.current_url != f"{base_url}{current_ep}/":
                    self.driver.get(f"{base_url}{current_ep}/")
                    time.sleep(3)

                if "404" in self.driver.title or "Not Found" in self.driver.page_source:
                    print(f"{Colors.RED}  -> Episode {current_ep} not found. Stopping loop.{Colors.END}")
                    break

                try:
                    download_btn = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.ID, "download-btn"))
                    )
                    self.driver.execute_script("arguments[0].click();", download_btn)
                    print(f"{Colors.GREEN}  -> Clicked 'Download' button.{Colors.END}")
                except:
                    print(f"{Colors.YELLOW}  -> Could not find 'Download' button for Ep {current_ep}. Checking for direct links...{Colors.END}")
                
                time.sleep(2)
                try:
                    WebDriverWait(self.driver, 5).until(
                        EC.visibility_of_element_located((By.ID, "download-links"))
                    )
                    print(f"{Colors.GREEN}  -> Download modal opened.{Colors.END}")
                except:
                    pass
                
                time.sleep(1)
                links = self.driver.find_elements(By.XPATH, "//div[@id='download-links']//a[contains(@href, 'kwik')]")
                if links:
                    print(f"{Colors.GREEN}  -> Download links populated.{Colors.END}")
                else:
                    print(f"{Colors.YELLOW}  -> Modal or links did not load. Trying to find links on page...{Colors.END}")
                    
                links = self.driver.find_elements(By.XPATH, "//div[@id='download-links']//a[contains(@href, 'kwik')] | //a[contains(@href, 'kwik')]")
                
                if not links:
                    print(f"{Colors.RED}  -> No Kwik links found for Ep {current_ep}. Stopping.{Colors.END}")
                    break
                    
                selected_link = None
                
                candidates = []
                for link in links:
                    text = link.text.strip()
                    candidates.append((link, text))
                
                if target_type:
                    type_matches = [c for c in candidates if target_type.lower() in c[1].lower()]
                    if type_matches:
                        candidates = type_matches
                        print(f"{Colors.CYAN}  -> Filtered by Type '{target_type}': {[c[1] for c in candidates]}{Colors.END}")
                
                if target_quality:
                    quality_matches = [c for c in candidates if target_quality in c[1]]
                    if quality_matches:
                        selected_link = quality_matches[0][0]
                        print(f"{Colors.GREEN}  -> Found match for Quality '{target_quality}'{Colors.END}")
                
                if not selected_link and candidates:
                    selected_link = candidates[0][0]
                    print(f"{Colors.YELLOW}  -> No exact quality match, selecting first available: '{candidates[0][1]}'{Colors.END}")
                
                if selected_link:
                    print(f"{Colors.MAGENTA}  -> Selected Link: '{selected_link.text}'{Colors.END}")
                    
                    self.driver.execute_script("arguments[0].scrollIntoView();", selected_link)
                    time.sleep(1)
                    
                    original_window = self.driver.current_window_handle
                    self.driver.execute_script("arguments[0].click();", selected_link)
                    print("  -> Clicked link, waiting for new tab...")
                    time.sleep(3)
                    
                    all_windows = self.driver.window_handles
                    kwik_window = None
                    
                    for window_handle in all_windows:
                        if window_handle != original_window:
                            self.driver.switch_to.window(window_handle)
                            current_url = self.driver.current_url.lower()
                            if 'kwik' in current_url or 'mewcdn' in current_url:
                                kwik_window = window_handle
                                print(f"  -> Found Kwik tab: {self.driver.current_url}")
                                break
                    
                    for window_handle in all_windows:
                        if window_handle != original_window and window_handle != kwik_window:
                            self.driver.switch_to.window(window_handle)
                            print(f"  -> Closing ad tab: {self.driver.current_url}")
                            self.driver.close()
                    
                    if kwik_window:
                        self.driver.switch_to.window(kwik_window)
                        print(f"  -> Switched to Kwik: {self.driver.current_url}")
                    else:
                        new_window = None
                        for window_handle in self.driver.window_handles:
                            if window_handle != original_window:
                                new_window = window_handle
                                break
                        
                        if new_window:
                            self.driver.switch_to.window(new_window)
                            print(f"  -> Switched to: {self.driver.current_url}")
                    
                    if kwik_window or new_window:
                        
                        try:

                            print(f"{Colors.CYAN}  -> Waiting 5 seconds for page to stabilize...{Colors.END}")
                            time.sleep(5)

                            from selenium.webdriver.common.action_chains import ActionChains
                            
                            try:
                                start_btn = self.driver.find_elements(By.ID, "download-start")
                                if start_btn:
                                    print("  -> Found 'download-start' button. Clicking it first...")
                                    ActionChains(self.driver).move_to_element(start_btn[0]).click().perform()
                                    time.sleep(3)
                                
                                form = self.driver.find_element(By.TAG_NAME, "form")
                                submit_btn = form.find_element(By.XPATH, ".//button | .//input[@type='submit']")
                                
                                if submit_btn:
                                    print(f"  -> Found form submit button: {submit_btn.text.strip()}")
                                    self.driver.execute_script("arguments[0].scrollIntoView();", submit_btn)
                                    time.sleep(1)
                                    print("  -> Clicking form button via ActionChains...")
                                    ActionChains(self.driver).move_to_element(submit_btn).click().perform()
                                else:
                                    raise Exception("No form button")
                                    
                            except Exception as e:
                                error_msg = str(e).split('\n')[0]
                                print(f"{Colors.YELLOW}  -> Primary click failed, trying fallback...{Colors.END}")
                                dl_btns = self.driver.find_elements(By.XPATH, "//button[contains(text(), 'Download')] | //a[contains(text(), 'Download')]")
                                for btn in dl_btns:
                                    if btn.is_displayed():
                                        print(f"{Colors.GREEN}  -> Fallback: Clicking visible button '{btn.text}'{Colors.END}")
                                        ActionChains(self.driver).move_to_element(btn).click().perform()
                                        break
                            
                            if self.monitor_download(current_ep):
                                downloaded_episodes.append(current_ep)
                                consecutive_errors = 0
                            else:
                                print(f"  -> Download failed for Ep {current_ep}")
                                consecutive_errors += 1
                            
                        except Exception as e:
                            print(f"  -> Could not initiate download: {e}")
                            consecutive_errors += 1
                        
                        self.driver.close()
                        self.driver.switch_to.window(original_window)
                    else:
                        print("  -> Failed to open new tab.")
                        consecutive_errors += 1
                else:
                    print("  -> No valid link found.")
                    consecutive_errors += 1

            except Exception as e:
                print(f"  -> Error scraping Ep {current_ep}: {e}")
                consecutive_errors += 1
            
            if consecutive_errors >= 3:
                print("  -> Too many consecutive errors. Stopping.")
                break
                
            current_ep += 1
            
        return downloaded_episodes

    def _loading_animation(self, duration, message="Processing"):
        """
        Displays a 'hacking style' progress animation.
        """
        end_time = time.time() + duration
        chars = "█▓▒░ "
        width = 20
        
        while time.time() < end_time:
            for i in range(width + 1):
                if time.time() >= end_time: break
                bar = "█" * i + "░" * (width - i)
                sys.stdout.write(f"\r{message} [{bar}] {int((i/width)*100)}%")
                sys.stdout.flush()
                time.sleep(0.05)
            
            for i in range(width, -1, -1):
                if time.time() >= end_time: break
                bar = "█" * i + "░" * (width - i)
                sys.stdout.write(f"\r{message} [{bar}] {int((i/width)*100)}%")
                sys.stdout.flush()
                time.sleep(0.05)
                
        sys.stdout.write("\r" + " " * (len(message) + width + 10) + "\r")
        sys.stdout.flush()

    def close(self):
        self.driver.quit()

def print_intro():
    art = f"""{Colors.CYAN}{Colors.BOLD}
    ██ ▄█▀▄▄▄       ██▓ ▒███████▒▓█████  ███▄    █ 
    ██▄█▒▒████▄    ▓██▒ ▒ ▒ ▒ ▄▀░▓█   ▀  ██ ▀█   █ 
   ▓███▄░▒██  ▀█▄  ▒██▒ ░ ▒ ▄▀▒░ ▒███   ▓██  ▀█ ██▒
   ▓██ █▄░██▄▄▄▄██ ░██░   ▄▀▒   ░▒▓█  ▄ ▓██▒  ▐▌██▒
   ▒██▒ █▄▓█   ▓██▒░██░ ▒███████▒░▒████▒▒██░   ▓██░
   ▒ ▒▒ ▓▒▒▒   ▓▒█░░▓   ░▒▒ ▓░▒░▒░░ ▒░ ░░ ▒░   ▒ ▒ 
   ░ ░▒ ▒░ ▒   ▒▒ ░ ▒ ░ ░░▒ ▒ ░ ▒ ░ ░  ░░ ░░   ░ ▒░
   ░ ░░ ░  ░   ▒    ▒ ░ ░ ░ ░ ░ ░   ░      ░   ░ ░ 
   ░  ░        ░  ░ ░     ░ ░       ░  ░         ░ 
                          ░                        
    {Colors.END}"""
    for line in art.split("\n"):
        print(line)
        time.sleep(0.05)
    print(f"\n written by {Colors.RED}TREX{Colors.END} between keystrokes and caffeine")
    print(f"\n{Colors.GREEN}{"="*50}")
    print(f"{Colors.YELLOW}{Colors.BOLD}   SYSTEM ONLINE // INITIATING DOWNLOAD PROTOCOL{Colors.END}")
    print(f"{Colors.GREEN}{"="*50}{Colors.END}\n")
    time.sleep(1)

if __name__ == "__main__":
    import re
    
    print_intro()
    
    url_input = input(">> ENTER TARGET URL: ").strip()
    
    match = re.search(r"9anime\.org\.lv/([^/]+)-episode-(\d+)/?", url_input)
    
    if match:
        full_slug = match.group(1)
        start_ep = int(match.group(2))
        
        base_url = f"https://9anime.org.lv/{full_slug}-episode-"
        
        folder_name = full_slug
        if not os.path.exists(folder_name):
            os.makedirs(folder_name)
            print(f"{Colors.GREEN}>> CREATING DIRECTORY: {Colors.CYAN}{folder_name}{Colors.END}")
        else:
            print(f"{Colors.YELLOW}>> TARGET DIRECTORY: {Colors.CYAN}{folder_name}{Colors.END}")
            
        download_dir = os.path.abspath(folder_name)
        
    else:
        print(f"{Colors.RED}>> INVALID URL FORMAT. ENGAGING DEFAULT PROTOCOLS.{Colors.END}")
        base_url = "https://9anime.org.lv/gachiakuta-dub-episode-"
        start_ep = 1
        download_dir = os.path.abspath("downloads")
        if not os.path.exists(download_dir):
            os.makedirs(download_dir)
            print(f"{Colors.GREEN}>> CREATING DIRECTORY: {Colors.CYAN}downloads{Colors.END}")
        else:
            print(f"{Colors.YELLOW}>> USING DIRECTORY: {Colors.CYAN}downloads{Colors.END}")

    quality_input = input(">> TARGET QUALITY (e.g. 720p) [ENTER for ANY]: ").strip()
    type_input = input(">> TARGET TYPE (e.g. Dub) [ENTER for ANY]: ").strip()
    
    if not quality_input: quality_input = None
    if not type_input: type_input = None
    
    print(f"\n>> INITIATING SCRAPER...")
    print(f">> BASE URL: {base_url}")
    print(f">> START EPISODE:{Colors.CYAN} {start_ep} {Colors.END}")
    print(f">> OUTPUT DIR: {download_dir}")
    
    downloader = AnimeDownloader(download_dir=download_dir)
    
    try:
        completed = downloader.scrape_and_queue(start_ep, base_url, quality_input, type_input)
        
        print("\n" + "="*50)
        print("   MISSION REPORT")
        print("="*50)
        print(f"TOTAL UNITS ACQUIRED: {len(completed)}")
        print(f"EPISODES: {completed}")
        print(f"STORAGE LOCATION: {download_dir}")
        
    except KeyboardInterrupt:
        print("\n>> MISSION ABORTED BY USER.")
    except Exception as e:
        print(f"\n>> CRITICAL ERROR: {e}")
    finally:
        downloader.close()
        print(">> SYSTEM OFFLINE.")
