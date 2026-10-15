"""
Authentication and Authorization (RBAC) Module for PharmaVigil.

Provides:
- Secure SQLite database for users, sessions, and verification records.
- PBKDF2-HMAC-SHA256 password hashing with unique per-user cryptographic salts.
- Role-Based Access Control (RBAC): doctor, analyst, user.
- Doctor verification tracking with cryptographic signature hash.
- Pre-seeded demo credentials for instant evaluation.
"""

import sqlite3
import hashlib
import hmac
import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

DB_PATH = Path(__file__).resolve().parent.parent / "outputs" / "pharmavigil.db"


def get_db_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    target_path = db_path or DB_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target_path))
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    if not salt:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100000
    )
    return key.hex(), salt


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100000
    )
    return hmac.compare_digest(key.hex(), expected_hash)


def init_auth_db(db_path: Optional[Path] = None) -> None:
    """Initializes tables and seeds default accounts if needed."""
    conn = get_db_connection(db_path)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        role TEXT NOT NULL,
        full_name TEXT NOT NULL,
        medical_license TEXT,
        specialty TEXT,
        affiliation TEXT,
        created_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS verifications (
        verification_id TEXT PRIMARY KEY,
        report_id TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        doctor_name TEXT NOT NULL,
        medical_license TEXT NOT NULL,
        specialty TEXT,
        affiliation TEXT,
        decision TEXT NOT NULL,
        notes TEXT,
        verified_at_utc TEXT NOT NULL,
        signature_hash TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)
    conn.commit()

    # Seed demo accounts only when explicitly enabled. Never create known
    # credentials on a deployed service by default.
    cur.execute("SELECT COUNT(*) FROM users")
    count = cur.fetchone()[0]
    import os
    if count == 0 and os.environ.get("PHARMAVIGIL_SEED_DEMO_USERS", "").lower() in {"1", "true", "yes"}:
        now = datetime.now(timezone.utc).isoformat()

        # 1. Verified Doctor
        doc_hash, doc_salt = hash_password("doctor123")
        cur.execute("""
        INSERT INTO users (username, email, password_hash, salt, role, full_name, medical_license, specialty, affiliation, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "doctor@pharmavigil.org",
            "doctor@pharmavigil.org",
            doc_hash,
            doc_salt,
            "doctor",
            "Dr. Eleanor Vance, MD",
            "MED-PV-849201",
            "Cardiovascular Pharmacovigilance",
            "Clinical Safety Review Board",
            now
        ))

        # 2. Safety Analyst (Non-doctor role)
        ana_hash, ana_salt = hash_password("analyst123")
        cur.execute("""
        INSERT INTO users (username, email, password_hash, salt, role, full_name, medical_license, specialty, affiliation, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "analyst@pharmavigil.org",
            "analyst@pharmavigil.org",
            ana_hash,
            ana_salt,
            "analyst",
            "Alex Chen, MS",
            None,
            "Data Analytics",
            "Safety Data Operations",
            now
        ))
        conn.commit()

    conn.close()


def register_user(
    username: str,
    password: str,
    full_name: str,
    role: str = "analyst",
    email: Optional[str] = None,
    medical_license: Optional[str] = None,
    specialty: Optional[str] = None,
    affiliation: Optional[str] = None,
    db_path: Optional[Path] = None
) -> Dict[str, Any]:
    role = role.lower().strip()
    if role not in ("doctor", "verifier", "analyst", "user"):
        raise ValueError(f"Invalid role: {role}. Must be 'doctor', 'verifier', 'analyst', or 'user'.")

    if role in ("doctor", "verifier") and not medical_license:
        # Generate default clinical registration ID if omitted by user
        medical_license = f"MED-REG-{secrets.token_hex(3).upper()}"

    username = username.strip().lower()
    full_name = full_name.strip()
    email = (email or username).strip().lower()
    if not username or not full_name or not password:
        raise ValueError("Username, password, and full name are required.")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters long.")
    if len(password) > 256:
        raise ValueError("Password must be no more than 256 characters long.")

    p_hash, salt = hash_password(password)
    now = datetime.now(timezone.utc).isoformat()

    conn = get_db_connection(db_path)
    cur = conn.cursor()
    try:
        cur.execute("""
        INSERT INTO users (username, email, password_hash, salt, role, full_name, medical_license, specialty, affiliation, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            username,
            email,
            p_hash,
            salt,
            role,
            full_name.strip(),
            medical_license.strip() if medical_license else None,
            specialty.strip() if specialty else None,
            affiliation.strip() if affiliation else None,
            now
        ))
        user_id = cur.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise ValueError(f"Username or email '{username}' already exists.")

    cur.execute("SELECT id, username, email, role, full_name, medical_license, specialty, affiliation, created_at FROM users WHERE id = ?", (user_id,))
    user = dict(cur.fetchone())
    conn.close()
    return user


def authenticate_user(
    username_or_email: str,
    password: str,
    db_path: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    cur = conn.cursor()
    query = username_or_email.strip().lower()
    cur.execute("""
    SELECT id, username, email, password_hash, salt, role, full_name, medical_license, specialty, affiliation
    FROM users
    WHERE username = ? OR email = ?
    """, (query, query))
    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    if verify_password(password, row["salt"], row["password_hash"]):
        user_dict = dict(row)
        del user_dict["password_hash"]
        del user_dict["salt"]
        return user_dict
    return None


def create_user_session(user_id: int, days_valid: int = 7, db_path: Optional[Path] = None) -> str:
    token = f"pv_{secrets.token_urlsafe(32)}"
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=days_valid)

    conn = get_db_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO sessions (token, user_id, created_at, expires_at)
    VALUES (?, ?, ?, ?)
    """, (token, user_id, now.isoformat(), expires.isoformat()))
    conn.commit()
    conn.close()
    return token


def get_user_from_token(token: str, db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    if not token:
        return None

    clean_token = token.strip()
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    conn = get_db_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
    SELECT s.expires_at, u.id, u.username, u.email, u.role, u.full_name, u.medical_license, u.specialty, u.affiliation
    FROM sessions s
    JOIN users u ON s.user_id = u.id
    WHERE s.token = ?
    """, (clean_token,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    try:
        expires = datetime.fromisoformat(row["expires_at"])
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        # Treat malformed persisted expiry data as invalid rather than causing
        # an authentication endpoint error.
        return None
    if datetime.now(timezone.utc) > expires:
        # Token expired
        return None

    user = dict(row)
    del user["expires_at"]
    return user


def delete_session(token: str, db_path: Optional[Path] = None) -> None:
    clean_token = token.strip()
    if clean_token.lower().startswith("bearer "):
        clean_token = clean_token[7:].strip()

    conn = get_db_connection(db_path)
    cur = conn.cursor()
    cur.execute("DELETE FROM sessions WHERE token = ?", (clean_token,))
    conn.commit()
    conn.close()


def generate_verification_signature(
    report_id: str,
    doctor_name: str,
    license_no: str,
    decision: str,
    verified_at: str
) -> str:
    msg = f"{report_id}|{doctor_name}|{license_no}|{decision}|{verified_at}"
    return hmac.new(_verification_secret(), msg.encode("utf-8"), hashlib.sha256).hexdigest()


def _verification_secret() -> bytes:
    """Load a stable deployment secret; avoid exposing a plain hash as a signature."""
    import os

    configured = os.environ.get("PHARMAVIGIL_SIGNING_KEY")
    if configured:
        return configured.encode("utf-8")
    # Persist a random key alongside the local database so signatures survive
    # restarts. Deployments should set PHARMAVIGIL_SIGNING_KEY when storage is
    # ephemeral or multiple instances are used.
    key_path = DB_PATH.with_name(".signing_key")
    try:
        return key_path.read_bytes()
    except FileNotFoundError:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_bytes(32)
        try:
            with key_path.open("xb") as key_file:
                key_file.write(key)
        except FileExistsError:
            return key_path.read_bytes()
        try:
            key_path.chmod(0o600)
        except OSError:
            pass
        return key


def record_doctor_verification(
    report_id: str,
    doctor_user: Dict[str, Any],
    decision: str,
    notes: Optional[str] = None,
    db_path: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Persists an authentic, verified doctor sign-off with a cryptographic signature hash.
    Enforces that user must have doctor or verifier role.
    """
    if doctor_user.get("role") not in ("doctor", "verifier"):
        raise PermissionError(
            f"User '{doctor_user.get('username')}' has role '{doctor_user.get('role')}'. "
            "Only authenticated medical professionals with the Doctor/Verifier role may sign off."
        )

    verification_id = f"VERIF-{secrets.token_hex(6).upper()}"
    now_utc = datetime.now(timezone.utc).isoformat()
    doctor_name = doctor_user.get("full_name") or doctor_user.get("username")
    license_no = doctor_user.get("medical_license") or "VERIFIED-MD"

    sig_hash = generate_verification_signature(
        report_id=report_id,
        doctor_name=doctor_name,
        license_no=license_no,
        decision=decision,
        verified_at=now_utc
    )

    conn = get_db_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO verifications (
        verification_id, report_id, user_id, doctor_name, medical_license,
        specialty, affiliation, decision, notes, verified_at_utc, signature_hash
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        verification_id,
        report_id,
        doctor_user["id"],
        doctor_name,
        license_no,
        doctor_user.get("specialty"),
        doctor_user.get("affiliation"),
        decision,
        notes,
        now_utc,
        sig_hash
    ))
    conn.commit()
    conn.close()

    return {
        "verification_id": verification_id,
        "report_id": report_id,
        "doctor_name": doctor_name,
        "medical_license": license_no,
        "specialty": doctor_user.get("specialty"),
        "affiliation": doctor_user.get("affiliation"),
        "decision": decision,
        "notes": notes,
        "verified_at_utc": now_utc,
        "signature_hash": sig_hash
    }


def get_verification_by_report(report_id: str, db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
    SELECT verification_id, report_id, doctor_name, medical_license, specialty, affiliation, decision, notes, verified_at_utc, signature_hash
    FROM verifications
    WHERE report_id = ?
    ORDER BY verified_at_utc DESC
    LIMIT 1
    """, (report_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None
