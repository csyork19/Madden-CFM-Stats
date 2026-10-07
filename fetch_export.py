#!/usr/bin/env python3
"""Download the latest league export from Madden Exporter and rebuild the stats.

    python3 fetch_export.py                 # uses the account in EXPORTER_USER below
    python3 fetch_export.py --user syork --league 4796457
    python3 fetch_export.py --headless      # no window
    python3 fetch_export.py --save-login    # store your login in the macOS Keychain (one time)

What it does:
  1. Opens https://maddenexporter.com/data/<user>.
  2. If the site shows the sign-in page, fills in your email and password and signs in.
  3. Clicks "Download CSV" and saves the file into exports/.
  4. Unzips it and rebuilds league-data.js from every week folder it contains.

Where the login comes from (first match wins). Nothing is written into this file:
  - environment variables EXPORTER_EMAIL and EXPORTER_PASSWORD
  - the macOS Keychain, after you run:  python3 fetch_export.py --save-login
  - otherwise it asks you in the terminal (the password is not shown as you type)
The site also keeps you signed in between runs via the .exporter-profile folder
next to this script, so most runs skip the sign-in page entirely.

One-time setup:
    pip3 install playwright
    python3 -m playwright install chromium
"""
import argparse
import getpass
import os
import re
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
EXPORTER_USER = 'syork'
SITE = 'https://maddenexporter.com'
PROFILE_DIR = os.path.join(HERE, '.exporter-profile')
EXPORTS_DIR = os.path.join(HERE, 'exports')
KEYCHAIN_SERVICE = 'madden-exporter'
EXPORTER_EMAIL = 'csyork19@gmail.com'
EXPORTER_PASSWORD = 'FortNite97!'


# ---------------------------------------------------------------- login details

def keychain_get():
    """(email, password) from the macOS Keychain, or None."""
    if sys.platform != 'darwin':
        return None
    try:
        meta = subprocess.run(['security', 'find-generic-password', '-s', KEYCHAIN_SERVICE], capture_output=True, text=True)
        pw = subprocess.run(['security', 'find-generic-password', '-s', KEYCHAIN_SERVICE, '-w'], capture_output=True, text=True)
    except OSError:
        return None
    m = re.search(r'"acct"<blob>="([^"]*)"', meta.stdout)
    if meta.returncode or pw.returncode or not m:
        return None
    return m.group(1), pw.stdout.rstrip('\n')


def keychain_save():
    if sys.platform != 'darwin':
        sys.exit('--save-login uses the macOS Keychain. On other systems set EXPORTER_EMAIL and EXPORTER_PASSWORD instead.')
    email = input('Madden Exporter email: ').strip()
    password = getpass.getpass('Password (not shown): ')
    if not email or not password:
        sys.exit('Nothing saved.')
    subprocess.run(['security', 'delete-generic-password', '-s', KEYCHAIN_SERVICE], capture_output=True)
    r = subprocess.run(['security', 'add-generic-password', '-s', KEYCHAIN_SERVICE, '-a', email, '-w', password, '-U'], capture_output=True, text=True)
    if r.returncode:
        sys.exit('Could not save to the Keychain: ' + r.stderr.strip())
    print('Saved to the macOS Keychain as "%s". Remove it any time in Keychain Access.' % KEYCHAIN_SERVICE)


def credentials():
    email, password = os.environ.get('EXPORTER_EMAIL'), os.environ.get('EXPORTER_PASSWORD')
    if email and password:
        return email, password
    saved = keychain_get()
    if saved:
        return saved
    if sys.stdin.isatty():
        email = email or input('Madden Exporter email: ').strip()
        return email, getpass.getpass('Password (not shown): ')
    return None


def sign_in(page, PWTimeout):
    """Fill the site's sign-in form. True when it worked."""
    creds = credentials()
    if not creds or not all(creds):
        return False
    email, password = creds
    box = page.locator('input[type="email"], input[name="email"], input[autocomplete="email"], input[autocomplete="username"]').first
    if not box.count():
        box = page.get_by_label(re.compile(r'email', re.I)).first
    box.fill(email)
    page.locator('input[type="password"]').first.fill(password)
    page.get_by_role('button', name=re.compile(r'^\s*sign in\s*$', re.I)).first.click()
    try:
        page.wait_for_url(lambda u: '/login' not in u and '/signup' not in u, timeout=30000)
    except PWTimeout:
        return False
    print('signed in')
    return True


def is_export(d):
    return os.path.isfile(os.path.join(d, 'teams.csv')) and os.path.isdir(os.path.join(d, 'stats'))


def export_root(folder):
    """The folder inside an unzipped download that actually holds teams.csv + stats/."""
    if is_export(folder):
        return folder
    for base, dirs, _files in os.walk(folder):
        for d in dirs:
            p = os.path.join(base, d)
            if is_export(p):
                return p
    return None


def unique_path(path):
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 2
    while os.path.exists('%s-%d%s' % (stem, n, ext)):
        n += 1
    return '%s-%d%s' % (stem, n, ext)


def download(url, league, headless, login_wait, download_wait):
    try:
        from playwright.sync_api import TimeoutError as PWTimeout
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit('Playwright is not installed. Run:\n    pip3 install playwright\n    python3 -m playwright install chromium')

    os.makedirs(EXPORTS_DIR, exist_ok=True)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(PROFILE_DIR, headless=headless, accept_downloads=True)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            print('opening %s' % url)
            page.goto(url, wait_until='domcontentloaded')

            button = page.get_by_role('button', name=re.compile(r'download csv', re.I))
            if league:
                # the Download CSV button that follows the "League <id>" heading
                button = page.get_by_text(re.compile(r'League\s+%s\b' % re.escape(str(league)))).first.locator(
                    'xpath=following::button[contains(translate(normalize-space(.), "DOWNLOADCSV", "downloadcsv"), "download csv")][1]')
            else:
                button = button.first

            # signed out -> the site shows its sign-in form: fill it in, then go back to the data page
            try:
                button.wait_for(state='visible', timeout=8000)
            except PWTimeout:
                if page.locator('input[type="password"]').count():
                    if not sign_in(page, PWTimeout):
                        if headless:
                            sys.exit('Sign-in failed or no login is saved. Check the email/password, or run: python3 fetch_export.py --save-login')
                        print('Could not sign in automatically. Sign in in the browser window. Waiting up to %d s...' % login_wait)
                        try:
                            page.wait_for_url(lambda u: '/login' not in u and '/signup' not in u, timeout=login_wait * 1000)
                        except PWTimeout:
                            sys.exit('Timed out waiting for sign-in.')
                    if '/data/' not in page.url:
                        page.goto(url, wait_until='domcontentloaded')
                try:
                    button.wait_for(state='visible', timeout=30000)
                except PWTimeout:
                    sys.exit('No "Download CSV" button found on %s. Is there an export for this account%s?'
                             % (page.url, ' and league %s' % league if league else ''))

            # the button is disabled until the league's file list has loaded
            page.wait_for_function('b => !b.disabled', arg=button.element_handle(), timeout=60000)
            print('clicking Download CSV...')
            with page.expect_download(timeout=download_wait * 1000) as info:
                button.click()
            dl = info.value
            dest = unique_path(os.path.join(EXPORTS_DIR, dl.suggested_filename or 'madden-export.zip'))
            dl.save_as(dest)
            print('saved %s (%d KB)' % (dest, os.path.getsize(dest) // 1024))
            return dest
        finally:
            ctx.close()


def unpack(path):
    """Unzip a download next to itself and return the export folder inside it."""
    if not zipfile.is_zipfile(path):
        sys.exit('Downloaded %s, but it is not a zip of CSV files, so the stats were not rebuilt.' % path)
    target = unique_path(os.path.splitext(path)[0])
    with zipfile.ZipFile(path) as z:
        z.extractall(target)
    root = export_root(target)
    if not root:
        sys.exit('Unzipped to %s, but found no teams.csv + stats/ inside, so the stats were not rebuilt.' % target)
    return root


def rebuild(root):
    sys.path.insert(0, HERE)
    from build_league_data import build, to_js
    data = build(root)
    out = os.path.join(HERE, 'league-data.js')
    with open(out, 'w', encoding='utf-8') as fh:
        fh.write(to_js(data))
    print('export: %s' % root)
    print('weeks found: %s  (current: %s)' % (data['weeks'], data['currentWeek']))
    for n in data['notes']:
        print('  note: ' + n)
    print('wrote %s' % out)


def main():
    ap = argparse.ArgumentParser(description='Download the latest Madden Exporter CSV export and rebuild league-data.js')
    ap.add_argument('--user', default=os.environ.get('EXPORTER_USER', EXPORTER_USER), help='Madden Exporter username (default: %(default)s)')
    ap.add_argument('--league', default=os.environ.get('EXPORTER_LEAGUE', ''), help='league id, if the account has more than one export')
    ap.add_argument('--url', default='', help='full data page address (overrides --user)')
    ap.add_argument('--headless', action='store_true', help='run without a window')
    ap.add_argument('--save-login', action='store_true', help='store your email and password in the macOS Keychain, then exit')
    ap.add_argument('--no-build', action='store_true', help='download and unzip only')
    ap.add_argument('--login-wait', type=int, default=300, help='seconds to wait for you to sign in')
    ap.add_argument('--download-wait', type=int, default=180, help='seconds to wait for the file')
    a = ap.parse_args()
    if a.save_login:
        keychain_save()
        return

    url = a.url or '%s/data/%s' % (SITE, a.user)
    path = download(url, a.league, a.headless, a.login_wait, a.download_wait)
    root = unpack(path)
    print('unzipped to %s' % root)
    if not a.no_build:
        rebuild(root)


if __name__ == '__main__':
    main()