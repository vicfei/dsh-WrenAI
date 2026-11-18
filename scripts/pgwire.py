#!/usr/bin/env python3
"""pgwire — a minimal PostgreSQL frontend (wire protocol v3) client, stdlib only.

Scope: exactly what a read-only analytics engine needs — connect, authenticate
(trust / cleartext / MD5 / SCRAM-SHA-256), optionally upgrade to TLS
(sslmode=require), run one simple query, return text-format rows. Clean-room
from the public PostgreSQL frontend/backend protocol documentation; zero
dependencies, zero upstream code.

DSN: postgresql://user:password@host:port/database?sslmode=require|disable
Special characters in user/password must be percent-encoded (e.g. @ → %40).

Usage:
    cols, rows = pgwire.connect("postgresql://postgres:p%40ss@localhost:5432/db").query("SELECT 1 AS one")
"""
import base64, hashlib, hmac, secrets, socket, ssl, struct
from urllib.parse import unquote, urlparse, parse_qs


class PGError(Exception):
    """Server-reported error (ErrorResponse) or client-side protocol failure."""

    def __init__(self, fields):
        self.fields = fields or {}
        super().__init__(self.fields.get("M") or "PostgreSQL error")


def parse_dsn(dsn):
    u = urlparse(dsn)
    if u.scheme not in ("postgres", "postgresql"):
        raise PGError({"M": "not a postgresql:// DSN: %s" % dsn[:60]})
    sslmode = (parse_qs(u.query).get("sslmode") or ["disable"])[0]
    if sslmode not in ("disable", "require"):
        raise PGError({"M": "unsupported sslmode %r (disable|require)" % sslmode})
    return {"user": unquote(u.username or "") or "postgres",
            "password": unquote(u.password or ""),
            "host": u.hostname or "localhost",
            "port": u.port or 5432,
            "database": (u.path or "/").lstrip("/") or "postgres",
            "sslmode": sslmode}


class Connection:
    def __init__(self, dsn, timeout=30):
        self.p = parse_dsn(dsn)
        self.sock = socket.create_connection((self.p["host"], self.p["port"]), timeout=timeout)
        self.sock.settimeout(timeout)
        if self.p["sslmode"] == "require":
            self._start_tls()
        self.tag = ""
        self._startup()

    # -- wire helpers ------------------------------------------------------

    def _send(self, buf):
        self.sock.sendall(buf)

    def _msg(self, mtype, payload):
        self._send(mtype + struct.pack("!I", len(payload) + 4) + payload)

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise PGError({"M": "connection closed by server"})
            buf += chunk
        return buf

    def _recv_msg(self):
        mtype = self._recv_exact(1)
        (ln,) = struct.unpack("!I", self._recv_exact(4))
        return mtype, self._recv_exact(ln - 4)

    @staticmethod
    def _fields(body):
        # ErrorResponse/NoticeResponse: (1-byte code + c-string)* terminated by NUL
        out, i = {}, 0
        while i < len(body) and body[i:i + 1] != b"\x00":
            j = body.index(b"\x00", i + 1)
            out[body[i:i + 1].decode()] = body[i + 1:j].decode("utf-8", "replace")
            i = j + 1
        return out

    # -- session setup -----------------------------------------------------

    def _start_tls(self):
        self._send(struct.pack("!II", 8, 80877103))  # SSLRequest
        if self._recv_exact(1) != b"S":
            raise PGError({"M": "server refused TLS (sslmode=require)"})
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # local/LAN analytics; not a trust root
        self.sock = ctx.wrap_socket(self.sock)

    def _startup(self):
        params = [("user", self.p["user"]), ("database", self.p["database"]),
                  ("application_name", "dsh-wrenai")]
        payload = struct.pack("!I", 196608)  # protocol 3.0
        payload += b"".join(k.encode() + b"\x00" + v.encode() + b"\x00" for k, v in params) + b"\x00"
        self._send(struct.pack("!I", len(payload) + 4) + payload)
        while True:
            mtype, body = self._recv_msg()
            if mtype == b"E":
                raise PGError(self._fields(body))
            elif mtype == b"R":
                self._auth(body)
            elif mtype == b"Z":  # ReadyForQuery — authenticated, ready
                return
            # ParameterStatus 'S' / BackendKeyData 'K' / NoticeResponse 'N' ignored

    def _auth(self, body):
        (code,) = struct.unpack("!i", body[:4])
        if code == 0:      # AuthenticationOk
            return
        if code == 3:      # cleartext password
            self._msg(b"p", self.p["password"].encode() + b"\x00")
        elif code == 5:    # md5 (user+password, then +salt)
            inner = hashlib.md5((self.p["password"] + self.p["user"]).encode()).hexdigest().encode()
            self._msg(b"p", (b"md5" + hashlib.md5(inner + body[4:8]).hexdigest()).encode() + b"\x00")
        elif code == 10:   # SASL — SCRAM-SHA-256
            mechs = [m.decode() for m in body[4:].split(b"\x00") if m]
            if "SCRAM-SHA-256" not in mechs:
                raise PGError({"M": "no supported SASL mechanism; server offers %s" % mechs})
            self._scram()
        else:
            raise PGError({"M": "unsupported auth request code %d" % code})

    def _expect_auth(self):
        while True:
            mtype, body = self._recv_msg()
            if mtype == b"E":
                raise PGError(self._fields(body))
            if mtype == b"R":
                (code,) = struct.unpack("!i", body[:4])
                return code, body[4:].decode("utf-8", "replace")

    def _scram(self):
        pw = self.p["password"].encode()
        cnonce = base64.b64encode(secrets.token_bytes(18)).decode()
        cfirst_bare = "n=%s,r=%s" % (self.p["user"], cnonce)
        init = b"n,," + cfirst_bare.encode()
        self._msg(b"p", b"SCRAM-SHA-256\x00" + struct.pack("!i", len(init)) + init)
        code, sfirst = self._expect_auth()
        if code != 11:  # AuthenticationSASLContinue
            raise PGError({"M": "expected SASLContinue, got auth code %d" % code})
        attrs = dict(kv.split("=", 1) for kv in sfirst.split(","))
        snonce, salt, iters = attrs["r"], base64.b64decode(attrs["s"]), int(attrs["i"])
        if not snonce.startswith(cnonce):
            raise PGError({"M": "server nonce does not extend client nonce"})
        cfinal_wo = "c=biws,r=%s" % snonce
        salted = hashlib.pbkdf2_hmac("sha256", pw, salt, iters)
        ckey = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
        skey = hashlib.sha256(ckey).digest()
        authmsg = ("%s,%s,%s" % (cfirst_bare, sfirst, cfinal_wo)).encode()
        csig = hmac.new(skey, authmsg, hashlib.sha256).digest()
        proof = bytes(a ^ b for a, b in zip(ckey, csig))
        self._msg(b"p", ("%s,p=%s" % (cfinal_wo, base64.b64encode(proof).decode())).encode())
        code, sfinal = self._expect_auth()
        if code != 12:  # AuthenticationSASLFinal
            raise PGError({"M": "expected SASLFinal, got auth code %d" % code})
        v = dict(kv.split("=", 1) for kv in sfinal.split(",")).get("v")
        srvkey = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
        if v != base64.b64encode(hmac.new(srvkey, authmsg, hashlib.sha256).digest()).decode():
            raise PGError({"M": "SCRAM server signature mismatch (channel not authenticated)"})
        # AuthenticationOk follows in the _startup loop

    # -- simple query ------------------------------------------------------

    def query(self, sql):
        """Run one SQL statement; return (column_names, rows of str/None)."""
        self._msg(b"Q", sql.encode() + b"\x00")
        cols, rows, err = [], [], None
        while True:
            mtype, body = self._recv_msg()
            if mtype == b"T":       # RowDescription
                (n,) = struct.unpack("!h", body[:2])
                i = 2
                for _ in range(n):
                    j = body.index(b"\x00", i)
                    cols.append(body[i:j].decode())
                    i = j + 1 + 4 + 2 + 4 + 2 + 4 + 2  # table oid, attnum, typoid, typlen, typmod, format
            elif mtype == b"D":     # DataRow (text format)
                (n,) = struct.unpack("!h", body[:2])
                i, row = 2, []
                for _ in range(n):
                    (ln,) = struct.unpack("!i", body[i:i + 4])
                    i += 4
                    row.append(None if ln == -1 else body[i:i + ln].decode("utf-8", "replace"))
                    i += max(ln, 0)
                rows.append(row)
            elif mtype == b"C":     # CommandComplete
                self.tag = body[:-1].decode()
            elif mtype == b"E":     # ErrorResponse — surface after ReadyForQuery
                err = PGError(self._fields(body))
            elif mtype == b"Z":     # ReadyForQuery
                if err:
                    raise err
                return cols, rows
            # NoticeResponse 'N' / ParameterStatus 'S' ignored

    def close(self):
        try:
            self._msg(b"X", b"")
            self.sock.close()
        except OSError:
            pass


def connect(dsn, timeout=30):
    return Connection(dsn, timeout)


if __name__ == "__main__":  # self-test: pgwire.py <dsn> <sql>
    import sys
    con = connect(sys.argv[1])
    try:
        cols, rows = con.query(sys.argv[2])
        print("\t".join(cols))
        for r in rows:
            print("\t".join("" if v is None else v for v in r))
        print("(%s)" % con.tag, file=sys.stderr)
    finally:
        con.close()
