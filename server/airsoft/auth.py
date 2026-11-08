"""Referee PIN login.

A single 6-digit PIN unlocks /ref and the command API. Never committed: it is
read from $AIRSOFT_REF_PIN, else server/ref_pin.txt (gitignored). If neither
exists, one is generated, saved to ref_pin.txt, and printed in the log.
Logins live in a signed session cookie whose key is random per process, so
restarting the dashboard logs every referee out (by design: simple, and
nothing secret ever needs to be stored or committed).
"""
import hmac
import os
import secrets
import threading
import time

from flask import session

from . import config

REF_PIN_FILE = os.path.join(config.SERVER_DIR, "ref_pin.txt")
LOGIN_MAX_FAILS = 5           # wrong PINs per client before a lockout
LOGIN_LOCK_S = 60             # lockout length (s): 6 digits can't be brute-forced


def _load_ref_pin():
    pin = os.environ.get("AIRSOFT_REF_PIN", "").strip()
    if not pin:
        try:
            with open(REF_PIN_FILE) as f:
                pin = f.read().strip()
        except FileNotFoundError:
            pin = f"{secrets.randbelow(10**6):06d}"
            fd = os.open(REF_PIN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(pin + "\n")
            print(f"[dash] generated referee PIN {pin} (saved to {REF_PIN_FILE})")
    if len(pin) != 6 or not pin.isdigit():
        raise SystemExit(f"[dash] referee PIN must be exactly 6 digits (check {REF_PIN_FILE} "
                         "or $AIRSOFT_REF_PIN)")
    return pin


REF_PIN = _load_ref_pin()
_login_fails = {}             # client ip -> (fail count, locked-until epoch)
_login_lock = threading.Lock()


def is_ref():
    return bool(session.get("ref"))


def try_login(ip, pin):
    """Check a PIN attempt. Returns None on success (session is now a referee),
    or the error message to show."""
    now = time.time()
    with _login_lock:
        fails, until = _login_fails.get(ip, (0, 0.0))
    if now < until:
        return f"Too many wrong PINs. Try again in {int(until - now) + 1} s."
    if hmac.compare_digest(pin.strip(), REF_PIN):
        with _login_lock:
            _login_fails.pop(ip, None)
        session.permanent = True
        session["ref"] = True
        print(f"[dash] referee login from {ip}")
        return None
    fails += 1
    with _login_lock:
        _login_fails[ip] = (0, now + LOGIN_LOCK_S) if fails >= LOGIN_MAX_FAILS else (fails, 0.0)
    print(f"[dash] wrong referee PIN from {ip} ({fails})")
    return ("Wrong PIN. Locked for %d s." % LOGIN_LOCK_S) if fails >= LOGIN_MAX_FAILS \
        else "Wrong PIN."
