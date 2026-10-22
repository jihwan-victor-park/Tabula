"""
Email + password accounts and browser sessions.

- Passwords: scrypt (N=2^14, r=8, p=1) with a random salt; compared in constant time.
  An unknown email still costs one hash, so response time does not reveal which emails exist.
- Five wrong passwords in a row lock the account for 15 minutes. Every failure — unknown email, wrong
  password, locked account — gets the same answer, so sign-in does not reveal which emails have accounts.
- Sessions: a random token in an HttpOnly cookie; only its sha256 is stored. 14 days,
  extended while used; sign-out revokes it server-side.
- Accounts are users with auth_subject 'local|<email>'. Store access still comes only from
  memberships, exactly as for any other sign-in method.
- Invitations: the owner adds an email to the store and gets a one-time link (only its sha256 is
  stored). Without that link, nobody can sign up with an email that already has store access —
  otherwise whoever registered the address first would take over the invitation.

Not yet: email verification and password reset by email (no mail sending in this build).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from clawbot.domain import tenancy
from clawbot.domain.errors import PermissionDenied, StateConflict, ValidationFailed
from clawbot.persistence.models import Invitation, Membership, User, UserCredential, UserSession
from clawbot.policies.permissions import Actor

SESSION_TTL = timedelta(days=14)
LOCK_AFTER = 5
LOCK_FOR = timedelta(minutes=15)
INVITE_TTL = timedelta(days=14)
SIGN_IN_FAILED = "Email or password is not right. After 5 wrong tries, sign-in pauses for 15 minutes."
INVITE_ROLES = ("manager", "receiver", "bookkeeper")
MIN_PASSWORD = 10
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_N, _R, _P = 2**14, 8, 1


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(_hash(password, salt)).decode()}"


def _verify(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, base64.b64decode(digest))


_DUMMY = hash_password("not-a-real-password-for-timing")


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if not _EMAIL.match(email) or len(email) > 320:
        raise ValidationFailed("Enter a valid email address")
    return email


def check_password(password: str, email: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise ValidationFailed(f"Use at least {MIN_PASSWORD} characters")
    if password.strip().lower() == email.split("@")[0] or password.lower() in email:
        raise ValidationFailed("The password cannot be your email")


def invite(session: Session, *, tenant_id: uuid.UUID, actor: Actor, email: str, role: str) -> str | None:
    """
    Give an email access to the store. Returns the one-time sign-up token for someone without an account yet
    (shown once, to be passed on by the owner), or None when that email already has an account.
    Owners are not invited this way: an invite link is a bearer secret and must not carry approval rights.
    """
    email = normalize_email(email)
    if role not in INVITE_ROLES:
        raise ValidationFailed("Invite as manager, receiver or bookkeeper")
    membership = tenancy.set_member_role(session, tenant_id=tenant_id, actor=actor, auth_subject=f"local|{email}",
                                         email=email, role=role)
    if session.get(UserCredential, membership.user_id) is not None:
        return None
    token = secrets.token_urlsafe(32)
    session.add(Invitation(token_hash=_token_hash(token), user_id=membership.user_id, tenant_id=tenant_id,
                           invited_by=actor.user_id, expires_at=_now() + INVITE_TTL))
    session.flush()
    return token


def sign_up(session: Session, *, email: str, password: str, invite: str | None = None) -> User:
    email = normalize_email(email)
    check_password(password, email)
    subject = f"local|{email}"
    user = session.scalars(select(User).where(User.auth_subject == subject).with_for_update()).one_or_none()
    if user is not None and session.get(UserCredential, user.id) is not None:
        raise StateConflict("An account with this email already exists — sign in instead")
    if user is None:
        user = User(auth_subject=subject, email=email)
        session.add(user)
        session.flush()
    elif session.scalar(select(func.count()).select_from(Membership).where(Membership.user_id == user.id)):
        # This email was given store access. Only the holder of the invite link may set its password.
        found = None if not invite else session.scalars(select(Invitation).where(
            Invitation.token_hash == _token_hash(invite), Invitation.user_id == user.id,
            Invitation.used_at.is_(None), Invitation.expires_at > _now()).with_for_update()).one_or_none()
        if found is None:
            raise PermissionDenied("This email was invited to a store — open the invite link you were given to sign up")
        found.used_at = _now()
    session.add(UserCredential(user_id=user.id, password_hash=hash_password(password)))
    session.flush()
    return user


def sign_in(session: Session, *, email: str, password: str) -> User:
    try:
        email = normalize_email(email)
    except ValidationFailed:
        _verify(password, _DUMMY)
        raise PermissionDenied(SIGN_IN_FAILED)
    row = session.execute(select(User, UserCredential).join(UserCredential, UserCredential.user_id == User.id)
                          .where(User.auth_subject == f"local|{email}").with_for_update(of=UserCredential)).one_or_none()
    if row is None:
        _verify(password, _DUMMY)
        raise PermissionDenied(SIGN_IN_FAILED)
    user, cred = row
    if cred.locked_until and cred.locked_until > _now():
        _verify(password, _DUMMY)
        raise PermissionDenied(SIGN_IN_FAILED)
    if not _verify(password, cred.password_hash):
        cred.failed_attempts += 1
        if cred.failed_attempts >= LOCK_AFTER:
            cred.failed_attempts, cred.locked_until = 0, _now() + LOCK_FOR
        session.flush()
        raise PermissionDenied(SIGN_IN_FAILED)
    cred.failed_attempts, cred.locked_until, cred.updated_at = 0, None, _now()
    return user


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(session: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    session.add(UserSession(token_hash=_token_hash(token), user_id=user.id, expires_at=_now() + SESSION_TTL))
    session.flush()
    return token


def user_for_token(session: Session, token: str) -> User | None:
    row = session.scalars(select(UserSession).where(UserSession.token_hash == _token_hash(token))).one_or_none()
    now = _now()
    if row is None or row.revoked_at is not None or row.expires_at <= now:
        return None
    if now - row.last_seen_at > timedelta(hours=1):  # sliding expiry, written at most hourly
        row.last_seen_at, row.expires_at = now, now + SESSION_TTL
    return session.get(User, row.user_id)


def end_session(session: Session, token: str) -> None:
    row = session.scalars(select(UserSession).where(UserSession.token_hash == _token_hash(token))).one_or_none()
    if row is not None and row.revoked_at is None:
        row.revoked_at = _now()
