"""Selenium-based Gemini automation client."""

from __future__ import annotations

import atexit
import logging
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

try:  # pragma: no cover - import guard
    from selenium import webdriver
    from selenium.common.exceptions import NoSuchElementException, TimeoutException
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.firefox.options import Options as FirefoxOptions
    from selenium.webdriver.firefox.service import Service as FirefoxService
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
except ModuleNotFoundError as exc:  # pragma: no cover - import guard
    SELENIUM_AVAILABLE = False
    SELENIUM_IMPORT_ERROR = exc
else:  # pragma: no cover - import guard
    SELENIUM_AVAILABLE = True
    SELENIUM_IMPORT_ERROR = None


class GeminiClient:
    """High-level automation helper for interacting with Gemini via Firefox."""

    GEMINI_URL = "https://gemini.google.com/app"

    _PROFILE_SAFE_ENTRIES = (
        "cookies.sqlite",
        "cookies.sqlite-shm",
        "cookies.sqlite-wal",
        "storage",
        "webappsstore.sqlite",
        "webappsstore.sqlite-shm",
        "webappsstore.sqlite-wal",
        "prefs.js",
        "user.js",
        "addonStartup.json.lz4",
        "extensions.json",
        "sessionstore.jsonlz4",
    )

    INITIAL_RENDER_WAIT_SECONDS = 3
    RESPONSE_POLL_INTERVAL_SECONDS = 2
    RESPONSE_STABLE_CHECKS = 3

    def __init__(
        self,
        *,
        firefox_binary: str,
        firefox_profile_dir: Optional[str],
        timeout: int,
        auto_update_driver: bool,
        show_gui: bool,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.firefox_binary = firefox_binary
        self.firefox_profile_dir = firefox_profile_dir
        self.timeout = timeout
        self.auto_update_driver = auto_update_driver
        self.show_gui = show_gui

        self._logger = logger or logging.getLogger("prompt_enhancer.selenium_client")
        self._driver: Optional[webdriver.Firefox] = None
        self._profile_lock = threading.RLock()
        self._temp_profile_dir: Optional[str] = None
        self._atexit_registered = False

    # ------------------------------------------------------------------
    # Lifecycle management
    # ------------------------------------------------------------------

    def init_driver(self) -> None:
        if not SELENIUM_AVAILABLE:
            raise RuntimeError("selenium is not available") from SELENIUM_IMPORT_ERROR

        with self._profile_lock:
            if self._driver is not None:
                self._logger.info("existing Firefox session detected; closing before reinitializing")
                self.close()

        profile_dir = self.firefox_profile_dir or self._detect_default_firefox_profile()
        if not profile_dir:
            raise RuntimeError(
                "unable to detect Firefox profile directory; set SELENIUM_FIREFOX_PROFILE_DIR"
            )

        profile_path = Path(os.path.expanduser(profile_dir))
        if not profile_path.is_dir():
            raise RuntimeError(f"Firefox profile directory does not exist: {profile_path}")

        temp_profile = self._prepare_temp_profile(profile_path)

        options = FirefoxOptions()
        options.binary_location = self.firefox_binary
        if not self.show_gui:
            options.add_argument("-headless")
        options.profile = str(temp_profile)

        service = self._build_service()

        try:
            driver = webdriver.Firefox(options=options, service=service)
        except Exception as exc:  # pragma: no cover - depends on system setup
            self._cleanup_temp_profile()
            raise RuntimeError(f"failed to initialize Firefox: {exc}") from exc

        with self._profile_lock:
            self._driver = driver
        self._logger.info("Firefox WebDriver initialized")

    def close(self) -> None:
        with self._profile_lock:
            driver, self._driver = self._driver, None
        if driver is not None:
            try:
                driver.quit()
                self._logger.info("Firefox browser closed")
            except Exception as exc:  # pragma: no cover - depends on driver state
                self._logger.debug("unable to close Firefox cleanly: %s", exc)
        self._cleanup_temp_profile()

    # ------------------------------------------------------------------
    # Public interaction API
    # ------------------------------------------------------------------

    def send_query(self, text: str, max_retries: int = 2) -> str:
        last_error: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                driver = self._require_driver()
                self._open_gemini(driver)
                input_box = self._find_input_box(driver)
                self._submit_query(driver, input_box, text)
                self._wait_for_response(driver)
                return self._extract_response(driver)
            except Exception as exc:
                last_error = exc
                attempt_index = attempt + 1
                self._logger.warning(
                    "send_query attempt %s/%s failed: %s",
                    attempt_index,
                    max_retries,
                    exc,
                )
                if attempt_index >= max_retries:
                    raise
                self.close()
                try:
                    self.init_driver()
                except Exception:
                    self._logger.exception(
                        "failed to reinitialize Firefox driver after error"
                    )
                    raise
                self._logger.info("reinitialized Firefox driver; retrying")
        assert last_error is not None
        raise last_error

    # ------------------------------------------------------------------
    # Driver helpers
    # ------------------------------------------------------------------

    def _build_service(self) -> FirefoxService:
        if self.auto_update_driver:
            try:
                from webdriver_manager.firefox import GeckoDriverManager  # type: ignore
            except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
                raise RuntimeError(
                    "webdriver-manager is required when auto_update_driver is enabled"
                ) from exc
            driver_path = GeckoDriverManager().install()  # pragma: no cover - network dependent
            self._logger.info("using geckodriver at %s", driver_path)
            return FirefoxService(executable_path=driver_path)
        return FirefoxService()

    def _prepare_temp_profile(self, profile_path: Path) -> Path:
        temp_dir = Path(tempfile.mkdtemp(prefix="gemini_firefox_profile_"))
        self._logger.debug("creating isolated Firefox profile at %s", temp_dir)
        try:
            os.chmod(temp_dir, 0o700)
        except OSError as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise RuntimeError(f"failed to secure temporary Firefox profile directory: {exc}") from exc

        try:
            self._copy_profile_subset(profile_path, temp_dir)
            self._remove_firefox_locks(temp_dir)
        except Exception as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise RuntimeError(f"failed to copy Firefox profile: {exc}") from exc

        with self._profile_lock:
            self._cleanup_temp_profile()
            self._temp_profile_dir = str(temp_dir)
        self._register_atexit_cleanup()
        return temp_dir

    def _copy_profile_subset(self, profile_path: Path, temp_dir: Path) -> None:
        copied_any = False
        for entry in self._PROFILE_SAFE_ENTRIES:
            source = profile_path / entry
            if not source.exists():
                continue
            if source.is_symlink():
                self._logger.warning("skipping symlinked profile entry %s", source)
                continue
            destination = temp_dir / entry
            if source.is_dir():
                shutil.copytree(
                    source,
                    destination,
                    dirs_exist_ok=True,
                    copy_function=self._safe_copy_file,
                    ignore_dangling_symlinks=True,
                )
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                self._safe_copy_file(str(source), str(destination))
            copied_any = True

        if not copied_any:
            self._logger.warning("no whitelisted Firefox profile data copied from %s", profile_path)

    def _remove_firefox_locks(self, temp_dir: Path) -> None:
        for lock_name in ("parent.lock", ".parentlock", "lock"):
            lock_path = temp_dir / lock_name
            if lock_path.exists() or lock_path.is_symlink():
                try:
                    lock_path.unlink()
                except Exception as exc:  # pragma: no cover
                    self._logger.debug("unable to remove lock file %s: %s", lock_path, exc)

    def _safe_copy_file(self, src: str, dest: str) -> str:
        src_path = Path(src)
        if src_path.is_symlink():
            self._logger.warning("skipping symlinked profile file %s", src_path)
            return dest
        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest_path)
        return dest

    def _cleanup_temp_profile(self) -> None:
        with self._profile_lock:
            temp_dir, self._temp_profile_dir = self._temp_profile_dir, None
        if not temp_dir:
            return
        try:
            shutil.rmtree(temp_dir, ignore_errors=False)
            self._logger.debug("deleted temporary profile %s", temp_dir)
        except Exception as exc:  # pragma: no cover
            self._logger.debug("unable to delete %s: %s", temp_dir, exc)

    def _register_atexit_cleanup(self) -> None:
        if self._atexit_registered:
            return
        atexit.register(self._cleanup_temp_profile)
        self._atexit_registered = True

    def _detect_default_firefox_profile(self) -> Optional[str]:
        candidates = [
            "~/Library/Application Support/Firefox/Profiles",  # macOS
            "~/.mozilla/firefox",  # Linux
        ]
        for base in candidates:
            base_path = Path(os.path.expanduser(base))
            if not base_path.is_dir():
                continue
            try:
                entries = [p for p in base_path.iterdir() if p.is_dir()]
            except Exception:  # pragma: no cover - filesystem errors
                continue
            for suffix in (".default-release", ".default"):
                match = [p for p in entries if p.name.endswith(suffix)]
                if match:
                    return str(match[0])
            if entries:
                return str(entries[0])
        return None

    def _require_driver(self) -> webdriver.Firefox:
        with self._profile_lock:
            driver = self._driver
        if driver is None:
            raise RuntimeError("Firefox driver is not initialized")
        return driver

    # ------------------------------------------------------------------
    # Gemini interaction helpers
    # ------------------------------------------------------------------

    def _open_gemini(self, driver: webdriver.Firefox) -> None:
        self._logger.info("opening Gemini page")
        try:
            driver.get(self.GEMINI_URL)
            WebDriverWait(driver, 15).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            self._logger.info("if Gemini prompts for authentication, complete it in the browser window")
        except Exception as exc:
            raise RuntimeError(f"failed to open Gemini page: {exc}") from exc

    def _find_input_box(self, driver: webdriver.Firefox):
        self._logger.info("locating Gemini input box")
        selectors = [
            (By.CSS_SELECTOR, "rich-textarea[placeholder*='输入']"),
            (By.CSS_SELECTOR, "rich-textarea[placeholder*='Enter']"),
            (By.CSS_SELECTOR, "div[contenteditable='true']"),
            (By.CSS_SELECTOR, "textarea[placeholder*='输入']"),
            (By.CSS_SELECTOR, "textarea[placeholder*='Enter']"),
            (By.XPATH, "//rich-textarea"),
            (By.XPATH, "//div[@contenteditable='true']"),
        ]
        for by, selector in selectors:
            try:
                self._logger.debug("trying selector %s = %s", by, selector)
                element = WebDriverWait(driver, 8).until(EC.presence_of_element_located((by, selector)))
                self._logger.info("input box found via %s", selector)
                return element
            except TimeoutException:
                continue
        raise RuntimeError("could not locate Gemini input box; page layout may have changed")

    def _submit_query(self, driver, input_box, text: str) -> None:
        self._logger.info("submitting query (%d characters)", len(text))
        try:
            try:
                input_box.clear()
            except Exception:
                pass
            input_box.send_keys(text)
            try:
                input_box.send_keys(Keys.RETURN)
                self._logger.info("submitted query via Enter key")
                return
            except Exception:
                pass
            submit_candidates = [
                (By.CSS_SELECTOR, "button[aria-label*='Send']"),
                (By.CSS_SELECTOR, "button[aria-label*='发送']"),
                (By.CSS_SELECTOR, "button[type='submit']"),
                (By.XPATH, "//button[contains(@aria-label, 'Send') or contains(@aria-label, '发送')]")
            ]
            for by, selector in submit_candidates:
                try:
                    driver.find_element(by, selector).click()
                    self._logger.info("submitted query by clicking %s", selector)
                    return
                except Exception:
                    continue
            self._logger.warning("submit button not found; assuming Gemini accepted the text")
        except Exception as exc:
            raise RuntimeError(f"failed to submit query: {exc}") from exc

    def _wait_for_response(self, driver) -> None:
        timeout = self.timeout
        self._logger.info("waiting up to %ds for Gemini response", timeout)
        start = time.time()
        last_text = ""
        stable_count = 0
        required_stable = self.RESPONSE_STABLE_CHECKS

        time.sleep(self.INITIAL_RENDER_WAIT_SECONDS)
        while time.time() - start < timeout:
            try:
                stop_buttons = driver.find_elements(
                    By.XPATH,
                    "//button[contains(@aria-label, 'Stop') or contains(text(), 'Stop') or contains(@aria-label, '停止')]",
                )
                mic_buttons = driver.find_elements(
                    By.XPATH,
                    "//button[contains(@aria-label, 'microphone') or contains(@aria-label, '麦克风')]",
                )
                current_text = self._extract_response_text(driver)
                if current_text == last_text and current_text:
                    stable_count += 1
                else:
                    stable_count = 0
                    last_text = current_text
                if (not stop_buttons and current_text) or mic_buttons:
                    if stable_count >= required_stable:
                        self._logger.info("response stabilized")
                        return
            except Exception as exc:
                self._logger.debug("transient exception while waiting: %s", exc)
            time.sleep(self.RESPONSE_POLL_INTERVAL_SECONDS)
        self._logger.warning("timed out waiting for Gemini response")

    def _extract_response_text(self, driver) -> str:
        selectors = [
            (By.CSS_SELECTOR, "message-content"),
            (By.CSS_SELECTOR, ".model-response-text"),
            (By.CSS_SELECTOR, "div[data-test-id*='response']"),
            (By.XPATH, "//message-content"),
            (By.XPATH, "//div[contains(@class, 'response')]"),
            (By.XPATH, "//article//*[self::p or self::li or self::pre or self::code]")
        ]
        for by, selector in selectors:
            try:
                elements = driver.find_elements(by, selector)
                if elements:
                    text = (elements[-1].text or "").strip()
                    if text:
                        return text
            except Exception:
                continue
        return ""

    def _extract_response(self, driver) -> str:
        text = self._extract_response_text(driver)
        if text and len(text) > 10:
            self._logger.info("extracted response with %d characters", len(text))
            return text
        raise RuntimeError(
            "failed to extract Gemini response; ensure you are signed in and Gemini UI has not changed"
        )

